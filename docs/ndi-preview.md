# NDI® preview: what we learned

Notes from building the live preview of the server variant (`server/avmatrix/preview.py`, October 2026, NDI SDK
6.3.2 on a Raspberry Pi 4, Debian 13, Python 3.13). Language neutral: everything here applies to any
implementation that links `libndi`. Device protocols (Magewell `/mwapi`, BirdDog, Dante® ARC) are documented
in [devices.md](devices.md).

## Receiving

- **Use the official library.** NDI is not an open wire format; `libndi` (NDI SDK, Vizrt NDI AB) is the only
  supported receiver. It is a plain C API and easy to bind (`NDIlib_recv_create_v3`, `NDIlib_recv_capture_v2`,
  `NDIlib_recv_free_video_v2`, `NDIlib_recv_destroy`). The SDK is licensed separately and must not be
  redistributed with this project – install it from the vendor.
- **Lowest bandwidth** (`NDIlib_recv_bandwidth_lowest`) delivers the sender's proxy stream: 640×360 for the
  1080p and 720p sources we tried, at the source frame rate. Ask for `RGBX_RGBA` to get a packed 4-byte format
  that every image library accepts.
- **Give the receiver the address.** With `p_url_address = "ip:port"` (from mDNS `_ndi._tcp`, or from a decoder's
  source list) the first frame arrives ~30 ms after `recv_create`. No NDI finder is needed.
- **`libndi` needs `libavahi-client.so.3` at load time** on Linux, even if you never use its finder. If it is
  not installed system-wide, load a private copy first (`dlopen` with `RTLD_GLOBAL`), then `libndi`.

## NDI|HX

- HX sources (H.264/HEVC: many PTZ cameras and HDMI encoders) are **not decoded by `libndi` itself on Linux**.
  The library loads FFmpeg at run time (`libavcodec.so.61`, `libavutil.so.59` for SDK 6.3). Without them one
  HX source delivered no video frames at all, another one a full-size placeholder frame from the library
  ("Video decoder not found") at the source frame rate – which costs about 60 % of a Pi 4 core for nothing.
- Detect the missing decoder up front (`dlopen` both libraries) and report a state of its own
  (`unsupported_codec`) instead of "no signal"; drop the placeholder (full size, almost black) rather than
  showing it as a preview.
- With FFmpeg present HX works. A camera with a low-resolution HX stream (640×360, 25 fps) cost only ~14 % of a
  Pi 4 core at `recv_bandwidth_lowest` – less than a SpeedHQ proxy. Its full 1080p25 stream cost ~85 % and the
  Pi kept up with only 15 fps. Sources that offer nothing but the full picture should therefore be sampled
  rarely (open, wait for a key frame, one picture, close) and not be kept open for a "live" view.
- FFmpeg does not have to be installed system-wide: unpacking the distribution packages (libavcodec, libavutil
  and their missing dependencies) into a private directory and starting the process with `LD_LIBRARY_PATH`
  pointing there is enough. The path must be set before the process starts.
- The placeholder path leaked about 0.8 MB per receiver in our measurements; cache failures for a minute
  instead of retrying every few seconds, and guard the process with a memory limit.

## Cost (Raspberry Pi 4, one core = 100 %)

| State | CPU | Notes |
|---|---|---|
| receiver open on a 25 fps source, frames not even collected | ~20 % | the library decodes every frame in its own threads |
| receiver open, every frame collected | ~27 % | |
| one still: open, first frame, close, JPEG 320 px | ~50 ms of CPU | |
| live preview, 640×360, JPEG at 12.5 fps to one viewer | ~31 % | decode + JPEG |

Consequences:

- **Never keep receivers open for thumbnails.** Open, take the first frame, close. A handful of tiles refreshed
  every 4–5 s costs well under 1 % of a core on average.
- Keep an open receiver only for the one stream somebody is actually watching, and close it shortly after the
  last viewer left.
- Cap concurrent receivers; share one receiver (and one cached still) between all viewers of a source.
- Loading `libndi` adds roughly 35–40 MB resident memory to the process; load it lazily on the first request.
- Many short-lived receiver threads fragment glibc's malloc arenas: run with `MALLOC_ARENA_MAX=2`.

## Behaviour of senders

- **A static source sends one frame and then nothing.** Test pattern generators and paused players deliver the
  cached frame on connect and no further frames until the picture changes. "No new frame" therefore does not
  mean "no signal": for stills the first frame is enough; a live stream should repeat the last frame about once a
  second so the HTTP stream stays alive.
- "No signal" is: connected, but no frame within a few seconds. "Offline" is: the source is not announced at all
  (do not even open a receiver).
- Never show the last good picture after a source disappeared – show the state instead.

## Delivering to browsers

- Stills as plain JPEG with `Cache-Control: no-store`; fetch as blob and swap an object URL so the tile never
  flashes. Reserve the 16:9 box in the layout for every state.
- Live as MJPEG (`multipart/x-mixed-replace`): works in an `<img>` in every browser, needs no player. Drop
  frames for slow viewers instead of queueing. End the stream when the source is gone; the page should poll a
  small status endpoint, because browsers do not reliably fire `error` on a stalled MJPEG image.
