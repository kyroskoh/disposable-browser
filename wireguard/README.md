# WireGuard profiles

Put one `<profile>.conf` per VPN endpoint here (e.g. `mullvad-sg.conf`). Files are git-ignored
and mounted read-only into the controller at `/wg-profiles`. Request a session with
`{"network": "wireguard", "wireguard_profile": "mullvad-sg"}`.
