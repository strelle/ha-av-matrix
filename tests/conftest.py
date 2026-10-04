"""Shared fixtures."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Allow loading custom_components/av_matrix in every test."""
    return


@pytest.fixture
def session():
    from .fake_http import FakeSession

    return FakeSession()
