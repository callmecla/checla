import asyncio

import flet as ft

from checks import fx, network, prices, qr, scan

try:
    import flet_camera as fc
    import flet_permission_handler as fph
except ImportError:  # camera extras not installed: the scan button explains
    fc = fph = None

COLORS = {"ok": ft.Colors.GREEN, "warn": ft.Colors.ORANGE, "bad": ft.Colors.RED}
ICONS = {"ok": ft.Icons.CHECK_CIRCLE, "warn": ft.Icons.WARNING, "bad": ft.Icons.DANGEROUS}


def network_tab(page: ft.Page) -> ft.Control:
    verdict = ft.Text("", size=18, weight=ft.FontWeight.BOLD)
    results_col = ft.Column(spacing=8, scroll=ft.ScrollMode.AUTO, expand=True)
    progress = ft.ProgressRing(visible=False)
    button = ft.FilledButton("Check this network", icon=ft.Icons.WIFI_FIND)

    async def run(e):
        button.disabled = True
        progress.visible = True
        results_col.controls.clear()
        verdict.value = "Checking..."
        page.update()

        results = await asyncio.to_thread(network.run_all)
        level, msg = network.overall_verdict(results)
        verdict.value = msg
        verdict.color = COLORS[level]

        for r in results:
            results_col.controls.append(
                ft.ListTile(
                    leading=ft.Icon(ICONS[r.level], color=COLORS[r.level]),
                    title=ft.Text(r.domain),
                    subtitle=ft.Text(
                        f"Issuer: {r.issuer}" + ("\n" + "\n".join(r.notes) if r.notes else "")
                    ),
                )
            )
        button.disabled = False
        progress.visible = False
        page.update()

    button.on_click = run
    return ft.Column(
        [ft.Row([button, progress]), verdict, results_col],
        expand=True,
    )


def qr_tab(page: ft.Page) -> ft.Control:
    field = ft.TextField(
        label="Paste QR text or link",
        multiline=True,
        min_lines=3,
        max_lines=6,
    )
    out = ft.Column(spacing=6, scroll=ft.ScrollMode.AUTO, expand=True)
    progress = ft.ProgressRing(visible=False)
    button = ft.FilledButton("Inspect", icon=ft.Icons.QR_CODE_2)

    async def run(e):
        if not (field.value or "").strip():
            return
        button.disabled = True
        progress.visible = True
        out.controls.clear()
        page.update()

        r = await asyncio.to_thread(qr.analyze, field.value)

        out.controls.append(
            ft.Text(
                {"ok": "Looks fine", "warn": "Check before you pay", "bad": "Do not pay"}[r.level],
                size=18,
                weight=ft.FontWeight.BOLD,
                color=COLORS[r.level],
            )
        )
        for k, v in r.fields.items():
            out.controls.append(ft.Text(f"{k}: {v}", selectable=True))
        if len(r.hops) > 1:
            out.controls.append(ft.Text("Redirect chain:", weight=ft.FontWeight.BOLD))
            for i, h in enumerate(r.hops):
                out.controls.append(ft.Text(f"{i + 1}. {h}", selectable=True, size=12))
        for f in r.findings:
            out.controls.append(
                ft.ListTile(
                    leading=ft.Icon(ICONS[f.level], color=COLORS[f.level]),
                    title=ft.Text(f.text),
                    dense=True,
                )
            )
        button.disabled = False
        progress.visible = False
        page.update()

    button.on_click = run

    # ---- camera scanning (Android, iOS, or the browser build) ----
    scan_btn = ft.OutlinedButton("Scan with camera", icon=ft.Icons.CAMERA_ALT)
    scan_status = ft.Text("", size=12)
    cam_box = ft.Container(height=300, bgcolor=ft.Colors.BLACK, border_radius=8, visible=False)
    scan_state = {"gen": 0, "active": False}
    perms = fph.PermissionHandler() if fph else None
    if perms:
        page.services.append(perms)

    def camera_supported() -> bool:
        on_phone = page.platform in (ft.PagePlatform.ANDROID, ft.PagePlatform.IOS)
        return fc is not None and scan.available() and (page.web or on_phone)

    def close_camera() -> None:
        scan_state["active"] = False
        cam_box.content = None
        cam_box.visible = False
        scan_btn.content = "Scan with camera"
        scan_btn.icon = ft.Icons.CAMERA_ALT

    def stop_scan() -> None:
        """Called when the user leaves this tab, so the camera is released."""
        scan_state["gen"] += 1
        close_camera()
        scan_status.value = ""

    async def on_scan(e):
        if scan_state["active"]:
            stop_scan()
            page.update()
            return
        if not camera_supported():
            scan_status.value = (
                "Camera scanning works on Android, iOS, or in the browser "
                "(flet run --web). On desktop, paste the QR text instead."
            )
            page.update()
            return
        if not page.web and perms:
            status = await perms.request(fph.Permission.CAMERA)
            if status != fph.PermissionStatus.GRANTED:
                scan_status.value = "Camera permission denied. Enable it in system settings."
                page.update()
                return

        scan_state["gen"] += 1
        gen = scan_state["gen"]
        scan_state["active"] = True
        cam = fc.Camera(expand=True, preview_enabled=True)
        cam_box.content = cam
        cam_box.visible = True
        scan_btn.content, scan_btn.icon = "Stop scanning", ft.Icons.STOP
        scan_status.value = "Point the camera at a QR code..."
        out.controls.clear()
        page.update()

        found = None
        try:
            cams = await cam.get_available_cameras()
            if not cams:
                raise RuntimeError("no camera found")
            back = next((c for c in cams if c.lens_direction == fc.CameraLensDirection.BACK), cams[0])
            await cam.initialize(
                description=back,
                resolution_preset=fc.ResolutionPreset.MEDIUM,
                enable_audio=False,
                image_format_group=fc.ImageFormatGroup.JPEG,
            )
            while scan_state["active"] and scan_state["gen"] == gen:
                data = await cam.take_picture()
                found = await asyncio.to_thread(scan.decode_qr, data)
                if found:
                    break
                await asyncio.sleep(0.3)
        except Exception as ex:
            if scan_state["gen"] == gen and scan_state["active"]:
                scan_status.value = f"Camera error: {ex}"

        if scan_state["gen"] != gen:  # stopped or replaced while we were working
            return
        close_camera()
        if found:
            scan_status.value = "QR code read. Nothing was opened or paid."
            field.value = found
            page.update()
            await run(None)
        else:
            page.update()

    scan_btn.on_click = on_scan
    col = ft.Column(
        [field, ft.Row([button, scan_btn, progress], wrap=True), scan_status, cam_box, out],
        expand=True,
    )
    col.data = stop_scan
    return col


def prices_tab(page: ft.Page) -> ft.Control:
    monitor = prices.Monitor()
    state = {"gen": 0, "running": False}

    asset = ft.Dropdown(
        value=prices.ASSETS[0],
        options=[ft.dropdown.Option(a) for a in prices.ASSETS],
        width=120,
    )
    toggle = ft.FilledButton("Start", icon=ft.Icons.PLAY_ARROW)
    verdict = ft.Text("Press Start to poll exchanges every 5 seconds.", size=16, weight=ft.FontWeight.BOLD)
    detail = ft.Text("", size=12)
    rows = ft.Column(spacing=6, scroll=ft.ScrollMode.AUTO, expand=True)
    footnote = ft.Text(
        "Binance quotes USDT, the others USD, so ~0.1% gaps can be normal. "
        "First latency sample includes connection setup.",
        size=11,
        italic=True,
    )

    def render(snap: prices.Snapshot) -> None:
        verdict.value = snap.message
        verdict.color = COLORS[snap.level]
        detail.value = f"Median: {snap.median:,.2f}" if snap.median else ""
        if snap.notes:
            detail.value += ("   " if detail.value else "") + " ".join(snap.notes)
        rows.controls.clear()
        for q in snap.quotes:
            if q.ok:
                title = f"{q.exchange}   {q.mid:,.2f} {q.quote_ccy}"
                sub = (
                    f"{q.latency_ms:.0f} ms (avg {q.avg_latency_ms:.0f})   "
                    f"{q.divergence_pct:+.3f}% vs median   "
                    f"book spread {q.book_spread_pct:.3f}%"
                )
            else:
                title = q.exchange
                sub = f"Unreachable: {q.error}"
            rows.controls.append(
                ft.ListTile(
                    leading=ft.Icon(ICONS[q.level], color=COLORS[q.level]),
                    title=ft.Text(title),
                    subtitle=ft.Text(sub),
                    dense=True,
                )
            )

    async def loop(gen: int) -> None:
        while state["running"] and state["gen"] == gen:
            snap = await asyncio.to_thread(monitor.poll, asset.value)
            if not (state["running"] and state["gen"] == gen):
                break
            render(snap)
            page.update()
            await asyncio.sleep(5)

    async def on_toggle(e):
        if state["running"]:
            state["running"] = False
            toggle.content, toggle.icon = "Start", ft.Icons.PLAY_ARROW
            page.update()
            return
        state["running"] = True
        state["gen"] += 1
        toggle.content, toggle.icon = "Stop", ft.Icons.STOP
        verdict.value = "Polling..."
        page.update()
        page.run_task(loop, state["gen"])

    toggle.on_click = on_toggle
    return ft.Column(
        [ft.Row([asset, toggle]), verdict, detail, rows, footnote],
        expand=True,
    )


def fx_tab(page: ft.Page) -> ft.Control:
    state = {"mid": None, "quotes": []}

    src = ft.Dropdown(value="USD", label="Send", width=130,
                      options=[ft.dropdown.Option(c) for c in fx.CURRENCIES])
    dst = ft.Dropdown(value="PHP", label="Receive", width=130,
                      options=[ft.dropdown.Option(c) for c in fx.CURRENCIES])
    rate_btn = ft.OutlinedButton("Get rate", icon=ft.Icons.REFRESH)
    progress = ft.ProgressRing(visible=False, width=20, height=20)
    ref_text = ft.Text("", size=12)
    attribution = ft.Text(
        spans=[ft.TextSpan("Rates By Exchange Rate API", url="https://www.exchangerate-api.com")],
        size=11,
        visible=False,
    )

    name_f = ft.TextField(label="Provider (e.g. GCash, Wise)", dense=True)
    pays_f = ft.TextField(keyboard_type=ft.KeyboardType.NUMBER, dense=True, expand=True)
    gets_f = ft.TextField(keyboard_type=ft.KeyboardType.NUMBER, dense=True, expand=True)
    rate_f = ft.TextField(label="Rate shown by provider (optional)",
                          keyboard_type=ft.KeyboardType.NUMBER, dense=True, expand=True)
    add_btn = ft.FilledButton("Add quote", icon=ft.Icons.ADD)
    clear_btn = ft.TextButton("Clear all")
    msg = ft.Text("", size=12, color=ft.Colors.RED)
    verdict = ft.Text("", size=16, weight=ft.FontWeight.BOLD)
    results = ft.Column(spacing=4)

    def relabel() -> None:
        pays_f.label = f"You pay ({src.value})"
        gets_f.label = f"They receive ({dst.value})"

    relabel()

    def render() -> None:
        results.controls.clear()
        mid = state["mid"]
        if not (mid and state["quotes"]):
            verdict.value = ""
            return
        ranked = fx.rank(state["quotes"], mid.rate)
        best = ranked[0]
        verdict.value = f"Cheapest: {best.quote.name}, {best.cost_pct:.2f}% total cost"
        verdict.color = COLORS[best.level]
        for r in ranked:
            q = r.quote
            lines = [
                f"Pay {q.pays:,.2f} {mid.base}, they get {q.gets:,.2f} {mid.quote} "
                f"(effective rate {r.effective_rate:,.4f})",
                f"Reference would give {r.ideal_gets:,.2f}: you lose {r.lost_target:,.2f} {mid.quote} "
                f"(about {r.lost_source:,.2f} {mid.base})",
            ]
            if r.markup_pct is not None:
                lines.append(f"Rate markup {r.markup_pct:.2f}%, implied fee {r.implied_fee:,.2f} {mid.base}")
            lines += r.notes
            results.controls.append(
                ft.ListTile(
                    leading=ft.Icon(ICONS[r.level], color=COLORS[r.level]),
                    title=ft.Text(f"{q.name}   {r.cost_pct:.2f}%"),
                    subtitle=ft.Text("\n".join(lines), size=12),
                    trailing=ft.IconButton(
                        icon=ft.Icons.DELETE_OUTLINE, tooltip="Remove",
                        on_click=lambda e, q=q: remove(q),
                    ),
                    dense=True,
                )
            )

    def remove(q: fx.Quote) -> None:
        state["quotes"].remove(q)
        render()
        page.update()

    def on_pair_change(e) -> None:
        # quotes are in the old currencies, so they no longer apply
        state["mid"] = None
        state["quotes"].clear()
        relabel()
        ref_text.value = msg.value = verdict.value = ""
        attribution.visible = False
        results.controls.clear()
        page.update()

    src.on_select = on_pair_change
    dst.on_select = on_pair_change

    async def get_rate(e=None) -> bool:
        progress.visible = True
        msg.value = ""
        page.update()
        try:
            mid = await asyncio.to_thread(fx.fetch_mid, src.value, dst.value)
        except fx.RateError as ex:
            msg.value = str(ex)
            progress.visible = False
            page.update()
            return False
        state["mid"] = mid
        ref_text.value = (
            f"Reference: 1 {mid.base} = {mid.rate:,.4f} {mid.quote} ({mid.source}, {mid.date}). "
            "Daily rate, not live, so costs can be off by a few tenths of a percent."
        )
        attribution.visible = mid.source == "ExchangeRate-API"
        progress.visible = False
        render()
        page.update()
        return True

    def num(s: str | None) -> float:
        return float((s or "").replace(",", "").strip())

    async def on_add(e) -> None:
        msg.value = ""
        try:
            pays, gets = num(pays_f.value), num(gets_f.value)
            rate = num(rate_f.value) if (rate_f.value or "").strip() else None
        except ValueError:
            msg.value = "Enter numbers for the amounts (and the rate, if you fill it in)."
            page.update()
            return
        if pays <= 0 or gets <= 0 or (rate is not None and rate <= 0):
            msg.value = "Amounts and rate must be greater than zero."
            page.update()
            return
        if state["mid"] is None and not await get_rate():
            return
        name = (name_f.value or "").strip() or f"Provider {len(state['quotes']) + 1}"
        state["quotes"].append(fx.Quote(name, pays, gets, rate))
        # keep the pay amount: you usually compare providers for the same send amount
        name_f.value = gets_f.value = rate_f.value = ""
        render()
        page.update()

    def on_clear(e) -> None:
        state["quotes"].clear()
        render()
        page.update()

    rate_btn.on_click = get_rate
    add_btn.on_click = on_add
    clear_btn.on_click = on_clear

    return ft.Column(
        [
            ft.Row([src, dst, rate_btn, progress], wrap=True),
            ref_text,
            attribution,
            ft.Text(
                "Type what the provider's app shows. 'You pay' must include all fees.",
                size=12,
                italic=True,
            ),
            name_f,
            ft.Row([pays_f, gets_f]),
            ft.Row([rate_f]),
            ft.Row([add_btn, clear_btn]),
            msg,
            verdict,
            results,
        ],
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )


def placeholder(title: str) -> ft.Control:
    return ft.Container(ft.Text(f"{title}: coming soon"), alignment=ft.Alignment(0, 0), expand=True)


def main(page: ft.Page):
    page.title = "Checla"
    page.padding = 16

    tabs = [
        ("Network", ft.Icons.WIFI, network_tab(page)),
        ("QR", ft.Icons.QR_CODE_SCANNER, qr_tab(page)),
        ("Prices", ft.Icons.SHOW_CHART, prices_tab(page)),
        ("FX", ft.Icons.CURRENCY_EXCHANGE, fx_tab(page)),
    ]
    body = ft.Container(tabs[0][2], expand=True)

    def on_nav(e):
        leaving = body.content
        if callable(getattr(leaving, "data", None)):
            leaving.data()  # e.g. release the camera when leaving the QR tab
        body.content = tabs[e.control.selected_index][2]
        page.update()

    page.navigation_bar = ft.NavigationBar(
        destinations=[ft.NavigationBarDestination(icon=i, label=l) for l, i, _ in tabs],
        on_change=on_nav,
    )
    page.add(body)


if __name__ == "__main__":
    ft.run(main)
