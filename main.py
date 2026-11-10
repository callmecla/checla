import asyncio

import flet as ft

from checks import network, qr

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


def placeholder(title: str) -> ft.Control:
    return ft.Container(ft.Text(f"{title}: coming soon"), alignment=ft.alignment.center, expand=True)


def main(page: ft.Page):
    page.title = "Checla"
    page.padding = 16

    tabs = [
        ("Network", ft.Icons.WIFI, network_tab(page)),
        ("QR", ft.Icons.QR_CODE_SCANNER, qr_tab(page)),
        ("Prices", ft.Icons.SHOW_CHART, placeholder("Price and latency monitor")),
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


ft.app(target=main)
