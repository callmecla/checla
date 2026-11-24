# Checla

Check before you trust. A network and payment safety toolkit, built in Python with Flet.

## Modules (built one at a time)
1. Network integrity check: DNS vs DoH comparison and TLS issuer check on finance domains (done, v1)
2. QR payment inspector: EMVCo payment QR parsing and checksum, URL redirect chain (done: paste the text or scan with the camera)
3. Multi-exchange price and latency monitor: Binance, Coinbase, Kraken, Bitstamp polled every 5s (done, v1)
4. Remittance and FX true-cost calculator: you enter what each provider shows, it measures the real cost against a reference rate (done, v1)

## Run
```
pip install flet flet-camera flet-permission-handler httpx opencv-python-headless numpy
python main.py          # desktop window (camera scan not available on desktop)
flet run --web main.py  # browser (camera scan works here)
```

## Build
```
flet build apk --split-per-abi --yes -v   # Android; APKs land in build/apk (install the arm64-v8a one)
flet build ipa          # iOS (needs a Mac with Xcode)
```

## Requirements
Flet 1.x (`flet>=1.0`). Older 0.x releases use different names for several controls.

## Notes
- FX tab: reference rate comes from Frankfurter (ECB, no key; the v1 endpoint is deprecated but documented as working), with ExchangeRate-API's open endpoint as a fallback (rate limited, so cached for 1 hour; its terms require the attribution link the app shows). Both are daily rates, not live, so costs can be off by a few tenths of a percent. Providers' own comparison APIs (for example Wise's) need private tokens, so they are not used. Quotes are not saved because they go stale within minutes.
- Camera scan: takes a photo about every 0.4s and decodes it with OpenCV. flet-camera supports Android, iOS and web only, not Windows/macOS/Linux desktop. Scanning never opens the link or pays; it only analyzes the text.
- iOS needs `NSCameraUsageDescription` set in pyproject.toml (not configured yet; Android is).
- Price monitor: Binance quotes USDT, the others USD, so gaps of ~0.1% can be normal. Thresholds are warn at 0.3% and bad at 1.0% divergence from the median. It polls over HTTPS, so prices are a few seconds old; WebSockets would be the upgrade.
- No ICMP or raw sockets: probes are TCP, TLS and HTTPS only.
- A DNS mismatch alone is only a warning (CDNs vary by resolver). A mismatch plus a TLS failure is the real red flag.
