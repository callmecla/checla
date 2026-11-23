# Checla

Check before you trust. A network and payment safety toolkit, built in Python with Flet.

## Modules (built one at a time)
1. Network integrity check: DNS vs DoH comparison and TLS issuer check on finance domains (done, v1)
2. QR payment inspector: EMVCo payment QR parsing and checksum, URL redirect chain (done, paste-in; camera scan still to do)
3. Multi-exchange price and latency monitor: Binance, Coinbase, Kraken, Bitstamp polled every 5s (done, v1)
4. Remittance and FX fee comparer

## Run
```
pip install flet httpx
python main.py          # desktop window
flet run --web main.py  # browser
```

## Build
```
flet build apk          # Android
flet build ipa          # iOS (needs a Mac with Xcode)
```

## Requirements
Flet 1.x (`flet>=1.0`). Older 0.x releases use different names for several controls.

## Notes
- Price monitor: Binance quotes USDT, the others USD, so gaps of ~0.1% can be normal. Thresholds are warn at 0.3% and bad at 1.0% divergence from the median. It polls over HTTPS, so prices are a few seconds old; WebSockets would be the upgrade.
- No ICMP or raw sockets: probes are TCP, TLS and HTTPS only.
- A DNS mismatch alone is only a warning (CDNs vary by resolver). A mismatch plus a TLS failure is the real red flag.
