// Companion-Modul für den Strelle AV Matrix Server. Hält den Zustand über den Ereignis-Stream des Servers
// (Server-Sent Events) aktuell; Tasten werten ihn über Rückmeldungen (Feedbacks) aus.
const { InstanceBase, InstanceStatus, runEntrypoint, combineRgb, Regex } = require('@companion-module/base')

const RED = combineRgb(255, 75, 66) // Pult-UI: Program / aktiv
const AMBER = combineRgb(255, 176, 32) // Pult-UI: Preset / vorgewählt
const DARK = combineRgb(18, 18, 18)
const WHITE = combineRgb(255, 255, 255)
const BLACK = combineRgb(0, 0, 0)
const OFF = '__off__'

const slug = (text) =>
	String(text)
		.toLowerCase()
		.replace(/ä/g, 'ae')
		.replace(/ö/g, 'oe')
		.replace(/ü/g, 'ue')
		.replace(/ß/g, 'ss')
		.replace(/[^a-z0-9]+/g, '_')
		.replace(/^_+|_+$/g, '')

class AvMatrixInstance extends InstanceBase {
	async init(config) {
		this.config = config
		this.status = { routes: {}, presets: {}, can_undo: false }
		this.choices = { destinations: [], sources: [], presets: [] }
		this.choicesRev = null
		this.variableIds = ''
		this.abort = null
		this.stopped = false
		this.updateStatus(InstanceStatus.Connecting)
		this.defineAll()
		this.connect()
	}

	async destroy() {
		this.stopped = true
		clearTimeout(this.retry)
		if (this.abort) this.abort.abort()
	}

	async configUpdated(config) {
		this.config = config
		clearTimeout(this.retry)
		if (this.abort) this.abort.abort()
		this.connect()
	}

	getConfigFields() {
		return [
			{
				type: 'static-text',
				id: 'info',
				width: 12,
				label: 'Strelle AV Matrix Server',
				value: 'Läuft der Server auf demselben Rechner wie Companion, passen die Vorgaben (127.0.0.1, Port 8088).',
			},
			{ type: 'textinput', id: 'host', label: 'Adresse', width: 8, default: '127.0.0.1', regex: Regex.HOSTNAME },
			{ type: 'number', id: 'port', label: 'Port', width: 4, default: 8088, min: 1, max: 65535 },
		]
	}

	get base() {
		return `http://${this.config.host || '127.0.0.1'}:${this.config.port || 8088}`
	}

	// ------------------------------------------------------------ Verbindung zum Server
	async connect() {
		if (this.stopped) return
		const abort = new AbortController()
		this.abort = abort
		try {
			await this.loadChoices()
			const res = await fetch(`${this.base}/api/events`, { signal: abort.signal, headers: { Accept: 'text/event-stream' } })
			if (!res.ok || !res.body) throw new Error(`HTTP ${res.status}`)
			this.updateStatus(InstanceStatus.Ok)
			const decoder = new TextDecoder()
			let buffer = ''
			for await (const chunk of res.body) {
				buffer += decoder.decode(chunk, { stream: true })
				let end
				while ((end = buffer.indexOf('\n\n')) >= 0) {
					const block = buffer.slice(0, end)
					buffer = buffer.slice(end + 2)
					const data = block
						.split('\n')
						.filter((l) => l.startsWith('data:'))
						.map((l) => l.slice(5).trim())
						.join('\n')
					if (data) await this.onStatus(JSON.parse(data))
				}
			}
			throw new Error('Verbindung beendet')
		} catch (err) {
			if (this.stopped || abort !== this.abort || abort.signal.aborted) return
			this.updateStatus(InstanceStatus.ConnectionFailure, String(err.message || err))
			this.retry = setTimeout(() => this.connect(), 3000)
		}
	}

	async api(path, params) {
		const url = new URL(this.base + path)
		for (const [k, v] of Object.entries(params || {})) url.searchParams.set(k, v ?? '')
		const res = await fetch(url, { method: 'POST', signal: AbortSignal.timeout(15000) })
		const body = await res.json().catch(() => ({}))
		if (!res.ok) throw new Error(body.message || `HTTP ${res.status}`)
		return body
	}

	async loadChoices() {
		const res = await fetch(`${this.base}/api/choices`, { signal: AbortSignal.timeout(8000) })
		if (!res.ok) throw new Error(`HTTP ${res.status}`)
		this.choices = await res.json()
		this.defineAll()
	}

	async onStatus(status) {
		this.status = status
		if (status.choices_rev !== this.choicesRev) {
			this.choicesRev = status.choices_rev
			await this.loadChoices().catch((e) => this.log('warn', `Auswahllisten: ${e.message}`))
		}
		this.pushVariables()
		this.checkFeedbacks('route_active', 'preset_active', 'dest_empty')
	}

	// ------------------------------------------------------------ Namen ↔ Kennungen
	dest(value) {
		const want = String(value ?? '').trim().toLowerCase()
		return this.choices.destinations.find((d) => d.id === value) || this.choices.destinations.find((d) => d.id.toLowerCase() === want || d.name.toLowerCase() === want)
	}
	source(value, protocol) {
		if (value === OFF || value === '' || value == null) return null
		// frühere Namen (Gerät mit IP im Namen hat die Adresse gewechselt) gelten weiter
		if (this.choices.aliases && this.choices.aliases[value]) value = this.choices.aliases[value]
		const want = String(value).trim().toLowerCase()
		if (['aus', 'none', 'off'].includes(want)) return null
		const list = this.choices.sources.filter((s) => !protocol || s.protocol === protocol)
		const hit = list.find((s) => s.id === value) || list.find((s) => s.id.toLowerCase() === want || s.name.toLowerCase() === want)
		return hit ? hit.id : String(value)
	}
	preset(value) {
		const want = String(value ?? '').trim().toLowerCase()
		return this.choices.presets.find((p) => p.id === value) || this.choices.presets.find((p) => p.name.toLowerCase() === want)
	}
	sourceName(id) {
		if (id == null) return 'Aus'
		const hit = this.choices.sources.find((s) => s.id === id)
		return hit ? hit.name : id
	}
	short(name) {
		// "STUDIO-PC (Program)" → "Program"; "CH1@DA-22UC" bleibt
		const m = /\(([^)]+)\)\s*$/.exec(name)
		return m ? m[1] : name
	}

	// ------------------------------------------------------------ Definitionen
	defineAll() {
		const tag = { ndi: 'NDI', dante: 'Dante' }
		const destChoices = this.choices.destinations.map((d) => ({ id: d.id, label: `${tag[d.protocol] || d.protocol} · ${d.name}${d.protected ? ' (gesperrt)' : ''}` }))
		const sourceChoices = [{ id: OFF, label: 'Aus (keine Quelle)' }, ...this.choices.sources.map((s) => ({ id: s.id, label: `${tag[s.protocol] || s.protocol} · ${s.name}${s.name !== s.id ? ` – ${s.id}` : ''}` }))]
		const presetChoices = this.choices.presets.map((p) => ({ id: p.id, label: p.name }))
		const destOpt = { type: 'dropdown', id: 'dest', label: 'Ziel', choices: destChoices, default: destChoices[0]?.id ?? '', allowCustom: true, minChoicesForSearch: 8 }
		const sourceOpt = { type: 'dropdown', id: 'source', label: 'Quelle', choices: sourceChoices, default: OFF, allowCustom: true, minChoicesForSearch: 8 }
		const presetOpt = { type: 'dropdown', id: 'preset', label: 'Preset', choices: presetChoices, default: presetChoices[0]?.id ?? '', allowCustom: true }
		const run = async (what, fn) => {
			try {
				await fn()
			} catch (err) {
				this.log('error', `${what}: ${err.message || err}`)
			}
		}

		this.setActionDefinitions({
			route: {
				name: 'Verbindung setzen',
				description: 'Quelle auf Ziel schalten',
				options: [destOpt, sourceOpt],
				callback: (a) =>
					run('Verbindung setzen', async () => {
						const d = this.dest(a.options.dest)
						const id = d ? d.id : String(a.options.dest)
						await this.api('/api/route', { dest: id, source: this.source(a.options.source, d?.protocol) ?? '', origin: 'companion' })
					}),
			},
			preset_recall: {
				name: 'Preset abrufen',
				options: [presetOpt],
				callback: (a) => run('Preset abrufen', () => this.api('/api/preset/recall', { preset: this.preset(a.options.preset)?.id ?? String(a.options.preset), origin: 'companion' })),
			},
			undo_last: {
				name: 'Letzte Aktion rückgängig',
				options: [],
				callback: () => run('Rückgängig', () => this.api('/api/undo')),
			},
			undo_dest: {
				name: 'Ziel: vorherige Quelle',
				options: [destOpt],
				callback: (a) => run('Rückgängig', () => this.api('/api/undo', { dest: this.dest(a.options.dest)?.id ?? String(a.options.dest) })),
			},
		})

		this.setFeedbackDefinitions({
			route_active: {
				type: 'boolean',
				name: 'Verbindung aktiv',
				description: 'Wahr, solange genau diese Quelle auf diesem Ziel liegt',
				defaultStyle: { bgcolor: RED, color: BLACK },
				options: [destOpt, sourceOpt],
				callback: (fb) => {
					const d = this.dest(fb.options.dest)
					if (!d || !(d.id in this.status.routes)) return false
					return (this.status.routes[d.id] ?? null) === this.source(fb.options.source, d.protocol)
				},
			},
			preset_active: {
				type: 'boolean',
				name: 'Preset aktiv',
				description: 'Wahr, solange der Ist-Zustand dem Preset entspricht',
				defaultStyle: { bgcolor: RED, color: BLACK },
				options: [presetOpt],
				callback: (fb) => {
					const p = this.preset(fb.options.preset)
					return !!(p && this.status.presets[p.id])
				},
			},
			dest_empty: {
				type: 'boolean',
				name: 'Ziel hat keine Quelle',
				defaultStyle: { bgcolor: AMBER, color: BLACK },
				options: [destOpt],
				callback: (fb) => {
					const d = this.dest(fb.options.dest)
					return !!d && d.id in this.status.routes && this.status.routes[d.id] == null
				},
			},
		})

		// Variablen: aktuelle Quelle je Ziel, Zustand je Preset
		const defs = []
		this.varMap = []
		for (const d of this.choices.destinations) {
			const id = `ziel_${slug(d.name)}`
			if (defs.some((v) => v.variableId === id)) continue
			defs.push({ variableId: id, name: `Quelle auf ${d.name}` })
			this.varMap.push([id, d.id])
		}
		for (const p of this.choices.presets) defs.push({ variableId: `preset_${slug(p.id)}`, name: `Preset ${p.name} aktiv (1/0)` })
		const ids = defs.map((v) => v.variableId).join('|')
		if (ids !== this.variableIds) {
			this.variableIds = ids
			this.setVariableDefinitions(defs)
		}
		this.pushVariables()

		// Tasten-Vorlagen: je NDI-Decoder "Quelle auf Ziel", je Preset eine Taste
		const presets = {}
		const text = (t, size = 14) => ({ text: t, size, color: WHITE, bgcolor: DARK })
		for (const d of this.choices.destinations.filter((x) => x.protocol === 'ndi' && !x.protected)) {
			for (const s of [...this.choices.sources.filter((x) => x.protocol === 'ndi'), null]) {
				const sid = s ? s.id : OFF
				presets[`route_${slug(d.id)}_${slug(sid)}`] = {
					type: 'button',
					category: `Ziel: ${d.name}`,
					name: `${s ? s.name : 'Aus'} auf ${d.name}`,
					style: text(`${s ? this.short(s.name) : 'AUS'}\\n→ ${d.name}`),
					steps: [{ down: [{ actionId: 'route', options: { dest: d.id, source: sid } }], up: [] }],
					feedbacks: [{ feedbackId: 'route_active', options: { dest: d.id, source: sid }, style: { bgcolor: RED, color: BLACK } }],
				}
			}
		}
		for (const p of this.choices.presets) {
			presets[`preset_${slug(p.id)}`] = {
				type: 'button',
				category: 'Presets',
				name: `Preset ${p.name}`,
				style: text(`PRESET\\n${p.name}`),
				steps: [{ down: [{ actionId: 'preset_recall', options: { preset: p.id } }], up: [] }],
				feedbacks: [{ feedbackId: 'preset_active', options: { preset: p.id }, style: { bgcolor: RED, color: BLACK } }],
			}
		}
		presets.undo_last = {
			type: 'button',
			category: 'Allgemein',
			name: 'Letzte Aktion rückgängig',
			style: text('UNDO\\nletzte\\nAktion', 14),
			steps: [{ down: [{ actionId: 'undo_last', options: {} }], up: [] }],
			feedbacks: [],
		}
		this.setPresetDefinitions(presets)
	}

	pushVariables() {
		const values = {}
		for (const [id, dest] of this.varMap || []) values[id] = dest in this.status.routes ? this.sourceName(this.status.routes[dest]) : '?'
		for (const p of this.choices.presets) values[`preset_${slug(p.id)}`] = this.status.presets[p.id] ? 1 : 0
		this.setVariableValues(values)
	}
}

runEntrypoint(AvMatrixInstance, [])
