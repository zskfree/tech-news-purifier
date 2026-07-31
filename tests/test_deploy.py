from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_nginx_is_ip_port_only_without_domain_or_api_proxy() -> None:
    config = (ROOT / "deploy/nginx/tech-news-purifier.conf").read_text(encoding="utf-8")
    assert "listen 23654" in config
    assert "listen 80" not in config
    assert "listen 443" not in config
    assert "proxy_pass" not in config
    assert "280468.xyz" not in config
    assert "autoindex off" in config
    assert "location = / { return 404; }" in config


def test_legacy_proxy_deployment_assets_are_absent() -> None:
    assert not (ROOT / "deploy/scripts/update-cloudflare-ipsets").exists()
    assert not (ROOT / "deploy/systemd/cloudflare-ipset-update.timer").exists()
