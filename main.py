import asyncio

import flet as ft

from checks import network, prices, qr

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
    return ft.Column([field, ft.Row([button, progress]), out], expand=True)


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


def placeholder(title: str) -> ft.Control:
    return ft.Container(ft.Text(f"{title}: coming soon"), alignment=ft.Alignment(0, 0), expand=True)


def main(page: ft.Page):
    page.title = "Checla"
    page.padding = 16

    tabs = [
        ("Network", ft.Icons.WIFI, network_tab(page)),
        ("QR", ft.Icons.QR_CODE_SCANNER, qr_tab(page)),
        ("Prices", ft.Icons.SHOW_CHART, prices_tab(page)),
        ("FX", ft.Icons.CURRENCY_EXCHANGE, placeholder("Remittance and FX fees")),
    ]
    body = ft.Container(tabs[0][2], expand=True)

    def on_nav(e):
        body.content = tabs[e.control.selected_index][2]
        page.update()

    page.navigation_bar = ft.NavigationBar(
        destinations=[ft.NavigationBarDestination(icon=i, label=l) for l, i, _ in tabs],
        on_change=on_nav,
    )
    page.add(body)


if __name__ == "__main__":
    ft.run(main)
