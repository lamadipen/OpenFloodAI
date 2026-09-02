from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

from openfloodai.alerts.webhook import WebhookConfig
from openfloodai.common import SiteConfig
from openfloodai.edge.monitor import MonitorConfig, MonitorState
from openfloodai.edge.multi_site import MultiSiteConfig, SiteThread, run_multi_site
from openfloodai.ingestion.stream import StreamConfig


def _site(site_id: str = "test-site") -> SiteConfig:
    return SiteConfig(
        site_id=site_id,
        camera_id=f"cam-{site_id}",
        latitude=27.7,
        longitude=85.3,
    )


class TestMultiSiteConfig:
    def test_basic_creation(self) -> None:
        sites = [_site("s1"), _site("s2")]
        cfg = MultiSiteConfig(
            sites=sites,
            stream_urls={"s1": "rtsp://a", "s2": "rtsp://b"},
        )
        assert len(cfg.sites) == 2
        assert cfg.stream_urls["s1"] == "rtsp://a"
        assert cfg.webhooks == []
        assert cfg.target_fps == 1.0
        assert cfg.window_minutes == 10

    def test_with_webhooks(self) -> None:
        wh = WebhookConfig(url="https://example.com/hook")
        cfg = MultiSiteConfig(
            sites=[_site()],
            stream_urls={"test-site": "rtsp://x"},
            webhooks=[wh],
        )
        assert len(cfg.webhooks) == 1
        assert cfg.webhooks[0].url == "https://example.com/hook"


class TestSiteThread:
    def test_fields(self) -> None:
        config = MonitorConfig(
            site=_site(),
            stream=StreamConfig(url="rtsp://x"),
        )
        state = MonitorState()
        thread = threading.Thread(target=lambda: None, name="test")
        st = SiteThread(
            site_id="test-site",
            thread=thread,
            config=config,
            state=state,
        )
        assert st.site_id == "test-site"
        assert st.thread is thread
        assert st.config is config
        assert st.state is state


class TestRunMultiSite:
    def test_empty_stream_urls_returns_empty(self) -> None:
        cfg = MultiSiteConfig(
            sites=[_site("s1")],
            stream_urls={},
        )
        result = run_multi_site(cfg)
        assert result == {}

    def test_skips_sites_without_stream(self) -> None:
        cfg = MultiSiteConfig(
            sites=[_site("s1"), _site("s2")],
            stream_urls={"s1": "rtsp://a"},
        )
        with patch("openfloodai.edge.multi_site.run_monitor") as mock_run:
            # Make run_monitor return immediately
            mock_run.return_value = None
            result = run_multi_site(cfg)

        assert "s1" in result
        assert "s2" not in result

    @patch("openfloodai.edge.multi_site.run_monitor")
    def test_starts_all_matching_sites(self, mock_run: MagicMock) -> None:
        mock_run.return_value = None
        cfg = MultiSiteConfig(
            sites=[_site("s1"), _site("s2"), _site("s3")],
            stream_urls={"s1": "rtsp://a", "s2": "rtsp://b", "s3": "rtsp://c"},
        )
        result = run_multi_site(cfg)
        assert len(result) == 3
        assert mock_run.call_count == 3

    @patch("openfloodai.edge.multi_site.run_monitor")
    def test_threads_are_daemon(self, mock_run: MagicMock) -> None:
        mock_run.return_value = None
        cfg = MultiSiteConfig(
            sites=[_site("s1")],
            stream_urls={"s1": "rtsp://a"},
        )
        result = run_multi_site(cfg)
        assert result["s1"].thread.daemon is True
