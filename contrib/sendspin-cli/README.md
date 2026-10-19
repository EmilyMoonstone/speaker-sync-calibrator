# `--delay-playback` for sendspin-cpp-cli 0.3.0

Sendspin's static delay (`sendspin_static_delay` in Music Assistant, 0–5000 ms)
can only make a speaker play **earlier**. A speaker that sounds *ahead* of the
rest of its group therefore cannot be corrected from the server, and neither
can any speaker that has to wait for a slower one without a delay setting of
its own (a phone app over Bluetooth, say).

The sendspin-cpp library has always accepted a signed
`PlayerRoleConfig::fixed_delay_us` (positive plays earlier, negative later);
sendspin-cli 0.3.0 pins it to 0. [`0001-add-delay-playback.patch`](0001-add-delay-playback.patch)
adds `--delay-playback <ms>` (config key `delay-playback`, 0–5000) and passes
it in negated. It is fixed for the run: not remembered, not settable by a
server.

## How it is meant to be used with Speaker Sync Calibrator

Give the speaker that is too early a generous fixed hold-back — more than it is
ahead by, e.g. `delay-playback = 300` for a speaker 135 ms ahead. It then plays
later than everything else, which turns it back into an ordinary Sendspin
speaker: the calibration brings it forward with its static delay by exactly as
much as the current setup needs, and keeps doing so if the setup changes
(a phone on Bluetooth or not). Save one position per setup.

## Build and install (Debian 13, as root)

```bash
apt-get update && apt-get install -y build-essential cmake git pkg-config curl libasound2-dev libavahi-compat-libdnssd-dev
git clone --branch v0.3.0 --depth 1 https://github.com/Sendspin/sendspin-cpp-cli.git /usr/local/src/sendspin-cpp-cli-0.3.0
cd /usr/local/src/sendspin-cpp-cli-0.3.0
curl -fsSL https://raw.githubusercontent.com/EmilyMoonstone/speaker-sync-calibrator/main/contrib/sendspin-cli/0001-add-delay-playback.patch | git apply
cmake -B build -DCMAKE_BUILD_TYPE=Release && cmake --build build -j"$(nproc)"
ctest --test-dir build --output-on-failure
./build/sendspin-cli --version && ./build/sendspin-cli --help | grep -A5 delay-playback
```

Install over the release binary, keeping it for a rollback:

```bash
systemctl stop sendspin-cli
cp /usr/local/bin/sendspin-cli /usr/local/bin/sendspin-cli-0.3.0-release
cp build/sendspin-cli /usr/local/bin/sendspin-cli
echo 'delay-playback = 300' >> /etc/sendspin-cli.conf
systemctl start sendspin-cli && journalctl -u sendspin-cli -n 20 --no-pager | grep -E 'Holding|handshake|error'
```

Rollback:

```bash
systemctl stop sendspin-cli
sed -i '/^delay-playback/d' /etc/sendspin-cli.conf
cp /usr/local/bin/sendspin-cli-0.3.0-release /usr/local/bin/sendspin-cli
systemctl start sendspin-cli
```
