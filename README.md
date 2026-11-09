# Checla

Check before you trust. A network and payment safety toolkit, built in Python with Flet.

## Modules (built one at a time)
1. Network integrity check: DNS vs DoH comparison and TLS issuer check on finance domains (done, v1)
2. QR payment inspector (next)
3. Multi-exchange price and latency monitor
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

## Notes
- No ICMP or raw sockets: probes are TCP, TLS and HTTPS only.
- A DNS mismatch alone is only a warning (CDNs vary by resolver). A mismatch plus a TLS failure is the real red flag.
