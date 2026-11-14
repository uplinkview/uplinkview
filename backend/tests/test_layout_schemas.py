"""Schemat układu pulpitu: ścisła walidacja danych od użytkownika (bez bazy)."""

import pytest
from pydantic import ValidationError

from netpulse.api.layout_schemas import (
    ALLOWED_METRICS,
    MAX_WIDGETS,
    ChartConfig,
    DashboardLayout,
    RefreshPrefs,
)


def chart(**over):
    base = {
        "id": "c1",
        "type": "chart",
        "w": 6,
        "config": {"source": {"kind": "wan"}, "series": [{"key": "in_bps"}, {"key": "out_bps", "color": 2}]},
    }
    base["config"].update(over.pop("config", {}))
    base.update(over)
    return base


def layout(*widgets):
    return {"version": 1, "widgets": list(widgets)}


def test_valid_layout_and_defaults():
    parsed = DashboardLayout.model_validate(
        layout(
            {"id": "s", "type": "summary", "w": 12, "config": {"tiles": ["devices", "wan_down"]}},
            chart(),
            {"id": "d", "type": "devices", "w": 12},
        )
    )
    assert [w.type for w in parsed.widgets] == ["summary", "chart", "devices"]
    c = parsed.widgets[1].config
    assert c.chart == "area" and c.unit == "bits" and c.smooth is False and c.height == "md"
    assert c.range_min is None and c.refresh_s is None  # puste = ustawienia globalne
    assert parsed.widgets[2].config.kinds is None


def test_every_source_accepts_its_own_metrics():
    sources = {
        "wan": {"kind": "wan"},
        "interface": {"kind": "interface", "id": 3},
        "device": {"kind": "device", "id": 1},
        "wifi_total": {"kind": "wifi_total"},
        "wifi_network": {"kind": "wifi_network", "id": 7},
        "server": {"kind": "server"},
        "agent_cpu": {"kind": "agent_cpu", "id": 2},
        "agent_net": {"kind": "agent_net", "id": 2, "key": "eth0"},
        "agent_disk": {"kind": "agent_disk", "id": 2, "key": "sda"},
        "agent_temp": {"kind": "agent_temp", "id": 2, "key": "coretemp/Core 0"},
        "agent_container": {"kind": "agent_container", "id": 2, "key": "nextcloud"},
        "pve_guest": {"kind": "pve_guest", "id": 3, "key": "nextcloud (105)"},
        "snmp_sensor": {"kind": "snmp_sensor", "id": 5, "key": "cpu-temperature"},
        "snmp_poe": {"kind": "snmp_poe", "id": 5, "key": "ether5"},
        "snmp_sfp": {"kind": "snmp_sfp", "id": 5, "key": "sfp1"},
        "wan_latency": {"kind": "wan_latency", "id": 1, "key": "eth3"},
        "speedtest": {"kind": "speedtest", "id": 1, "key": "eth4"},
        "wan_ping": {"kind": "wan_ping", "id": 1, "key": "eth3 · google.com"},
        "vpn": {"kind": "vpn", "id": 1, "key": "iPhone"},
        "lan_client": {"kind": "lan_client", "id": 11, "key": "02:00:00:00:00:02"},
        "check": {"kind": "check", "id": 4},
    }
    assert set(sources) == set(ALLOWED_METRICS)
    for kind, source in sources.items():
        series = [{"key": k} for k in ALLOWED_METRICS[kind]]
        ChartConfig.model_validate({"source": source, "series": series[:6]})


def test_interface_and_wifi_sources_remember_their_device():
    for source in ({"kind": "interface", "id": 7, "device_id": 2}, {"kind": "wifi_network", "id": 3, "device_id": 4}):
        parsed = ChartConfig.model_validate({"source": source, "series": [{"key": "clients" if source["kind"] == "wifi_network" else "in_bps"}]})
        assert parsed.queries[0].source.device_id == source["device_id"]
    with pytest.raises(ValidationError):
        ChartConfig.model_validate({"source": {"kind": "interface", "id": 7, "device_id": 0}, "series": [{"key": "in_bps"}]})
    with pytest.raises(ValidationError):  # urządzenie i WAN nie mają pola device_id
        ChartConfig.model_validate({"source": {"kind": "wan", "device_id": 1}, "series": [{"key": "in_bps"}]})


@pytest.mark.parametrize(
    ("source", "key"),
    [
        ({"kind": "wan"}, "cpu_percent"),
        ({"kind": "device", "id": 1}, "in_bps"),
        ({"kind": "wifi_total"}, "rx_bps"),
        ({"kind": "interface", "id": 1}, "clients"),
    ],
)
def test_metric_must_belong_to_source(source, key):
    with pytest.raises(ValidationError, match="nie jest dostępna"):
        ChartConfig.model_validate({"source": source, "series": [{"key": key}]})


def test_rejects_duplicate_series_and_unknown_fields():
    with pytest.raises(ValidationError, match="nie mogą się powtarzać"):
        ChartConfig.model_validate({"source": {"kind": "wan"}, "series": [{"key": "in_bps"}, {"key": "in_bps"}]})
    with pytest.raises(ValidationError):
        DashboardLayout.model_validate(layout(chart(config={"nieznane": 1})))
    with pytest.raises(ValidationError):
        DashboardLayout.model_validate({"version": 1, "widgets": [], "dodatkowe": True})


@pytest.mark.parametrize(
    "bad",
    [
        {"w": 0},  # niedozwolona szerokość
        {"w": 13},
        {"id": ""},
        {"id": "ze spacją"},
        {"id": "x" * 41},
        {"type": "nieznany"},
        {"config": {"y_max": 0}},
        {"config": {"y_max": -5}},
        {"config": {"range_min": 45}},
        {"config": {"refresh_s": 7}},
        {"config": {"chart": "kołowy"}},
        {"config": {"unit": "megabits"}},
        {"config": {"height": "xl"}},
        {"config": {"series": []}},
        {"config": {"series": [{"key": "in_bps", "color": 9}]}},
        {"config": {"source": {"kind": "interface"}}},  # brak id
        {"config": {"source": {"kind": "interface", "id": 0}}},
        {"config": {"source": {"kind": "nieznane"}}},
    ],
)
def test_rejects_invalid_chart_widget(bad):
    with pytest.raises(ValidationError):
        DashboardLayout.model_validate(layout(chart(**bad)))


def test_rejects_too_long_title_and_trims_blank():
    with pytest.raises(ValidationError):
        ChartConfig.model_validate({"title": "x" * 81, "source": {"kind": "wan"}, "series": [{"key": "in_bps"}]})
    c = ChartConfig.model_validate({"title": "  Ruch  ", "source": {"kind": "wan"}, "series": [{"key": "in_bps"}]})
    assert c.title == "Ruch"
    assert ChartConfig.model_validate({"title": "   ", "source": {"kind": "wan"}, "series": [{"key": "in_bps"}]}).title is None


def test_widget_limits_and_unique_ids():
    many = [chart(id=f"w{i}") for i in range(MAX_WIDGETS)]
    DashboardLayout.model_validate(layout(*many))
    with pytest.raises(ValidationError):
        DashboardLayout.model_validate(layout(*many, chart(id="za-duzo")))
    with pytest.raises(ValidationError, match="unikalne"):
        DashboardLayout.model_validate(layout(chart(id="a"), chart(id="a")))


def test_summary_tiles_rules():
    with pytest.raises(ValidationError):
        DashboardLayout.model_validate(layout({"id": "s", "type": "summary", "w": 12, "config": {"tiles": []}}))
    with pytest.raises(ValidationError, match="nie mogą się powtarzać"):
        DashboardLayout.model_validate(layout({"id": "s", "type": "summary", "w": 12, "config": {"tiles": ["devices", "devices"]}}))
    with pytest.raises(ValidationError):
        DashboardLayout.model_validate(layout({"id": "s", "type": "summary", "w": 12, "config": {"tiles": ["cos"]}}))


def test_overview_widgets():
    """Od 0.42.0: pasek stanu, alerty, dostępność i tabela urządzeń."""
    parsed = DashboardLayout.model_validate(
        layout(
            {"id": "st", "type": "status", "w": 12},
            {"id": "al", "type": "alerts", "w": 4, "config": {"limit": 8}},
            {"id": "ch", "type": "checks", "w": 4},
            {"id": "ev", "type": "events", "w": 4},
            {"id": "d", "type": "devices", "w": 8, "config": {"display": "table"}},
        )
    )
    assert parsed.widgets[1].config.limit == 8
    assert parsed.widgets[2].config.days == 30
    assert (parsed.widgets[3].config.days, parsed.widgets[3].config.limit) == (7, 8)
    assert parsed.widgets[4].config.display == "table"
    # Stare pulpity bez pola `display` – karty jak dotąd
    assert DashboardLayout.model_validate(layout({"id": "d", "type": "devices", "w": 12})).widgets[0].config.display == "cards"
    for bad in (
        {"id": "al", "type": "alerts", "w": 4, "config": {"limit": 50}},
        {"id": "ch", "type": "checks", "w": 4, "config": {"days": 365}},
        {"id": "ev", "type": "events", "w": 4, "config": {"days": 2}},
        {"id": "st", "type": "status", "w": 12, "config": {"cos": 1}},
        {"id": "d", "type": "devices", "w": 8, "config": {"display": "lista"}},
    ):
        with pytest.raises(ValidationError):
            DashboardLayout.model_validate(layout(bad))


def test_only_schema_version_one_is_accepted():
    with pytest.raises(ValidationError):
        DashboardLayout.model_validate({"version": 2, "widgets": []})
    assert DashboardLayout.model_validate({"widgets": []}).version == 1


def test_roundtrip_is_stable():
    raw = layout(chart(config={"title": "Ruch", "chart": "bar", "unit": "bytes", "smooth": True, "y_max": 100.5, "range_min": 360}))
    parsed = DashboardLayout.model_validate(raw)
    again = DashboardLayout.model_validate(parsed.model_dump(mode="json"))
    assert again == parsed


def test_refresh_prefs():
    assert RefreshPrefs.model_validate({"interval_s": 0, "range_min": 15}).interval_s == 0
    for bad in ({"interval_s": 7, "range_min": 60}, {"interval_s": 30, "range_min": 5}, {"interval_s": 30}):
        with pytest.raises(ValidationError):
            RefreshPrefs.model_validate(bad)


def test_agent_source_needs_key_except_cpu():
    series = [{"key": "rx_bps"}]
    with pytest.raises(ValidationError):
        ChartConfig.model_validate({"source": {"kind": "agent_net", "id": 2, "key": "  "}, "series": series})
    cpu = ChartConfig.model_validate({"source": {"kind": "agent_cpu", "id": 2, "key": "x"}, "series": [{"key": "core_max_percent"}]})
    assert cpu.queries[0].source.key == ""
    with pytest.raises(ValidationError):  # metryka innego źródła z agenta
        ChartConfig.model_validate({"source": {"kind": "agent_net", "id": 2, "key": "eth0"}, "series": [{"key": "temp_c"}]})


def test_eight_series_colors():
    for color in range(1, 9):
        ChartConfig.model_validate({"source": {"kind": "wan"}, "series": [{"key": "in_bps", "color": color}]})
    with pytest.raises(ValidationError):
        ChartConfig.model_validate({"source": {"kind": "wan"}, "series": [{"key": "in_bps", "color": 0}]})


def test_wan_widgets():
    parsed = DashboardLayout.model_validate(
        layout(
            {"id": "a", "type": "wan_status", "w": 4},
            {"id": "b", "type": "wan_chart", "w": 8, "config": {"metric": "out_bps", "range_min": 1440, "device_id": 1}},
            {"id": "c", "type": "wan_sla", "w": 12, "config": {"days": 30}},
        )
    )
    assert parsed.widgets[0].config.device_id is None
    assert (parsed.widgets[1].config.metric, parsed.widgets[1].config.height) == ("out_bps", "md")
    assert parsed.widgets[2].config.days == 30
    assert DashboardLayout.model_validate(layout({"id": "c", "type": "wan_sla", "w": 6})).widgets[0].config.days == 7
    usage = DashboardLayout.model_validate(layout({"id": "u", "type": "wan_usage", "w": 4, "config": {"reset_day": 15, "limit_gb": 100}})).widgets[0]
    assert (usage.config.device_id, usage.config.reset_day, usage.config.limit_gb) == (None, 15, 100)
    assert DashboardLayout.model_validate(layout({"id": "u", "type": "wan_usage", "w": 4})).widgets[0].config.reset_day == 1
    for bad in (
        {"id": "u", "type": "wan_usage", "w": 4, "config": {"reset_day": 29}},
        {"id": "u", "type": "wan_usage", "w": 4, "config": {"limit_gb": 0}},
        {"id": "c", "type": "wan_sla", "w": 6, "config": {"days": 5}},
        {"id": "b", "type": "wan_chart", "w": 6, "config": {"metric": "clients"}},
        {"id": "a", "type": "wan_status", "w": 6, "config": {"cos": 1}},
    ):
        with pytest.raises(ValidationError):
            DashboardLayout.model_validate(layout(bad))


def test_long_ranges_from_hourly_aggregates():
    for minutes in (43200, 525600):
        parsed = DashboardLayout.model_validate(layout(chart(config={"range_min": minutes})))
        assert parsed.widgets[0].config.range_min == minutes
        assert RefreshPrefs.model_validate({"interval_s": 60, "range_min": minutes}).range_min == minutes


# --- wykres od 0.26.0: zapytania, osie, progi, legenda ----------------------------------------------


def test_legacy_chart_config_is_upgraded():
    parsed = ChartConfig.model_validate({"source": {"kind": "wan"}, "series": [{"key": "in_bps", "color": 2}], "y_max": 1e9, "chart": "line"})
    assert parsed.queries[0].id == "A" and parsed.queries[0].source.kind == "wan" and parsed.queries[0].offset_min == 0
    assert parsed.queries[0].series[0].color == 2 and parsed.queries[0].series[0].axis == "left"
    assert parsed.axes.left.max == 1e9 and parsed.chart == "line"
    assert parsed.legend.mode == "list" and parsed.thresholds == [] and not parsed.stack
    dumped = parsed.model_dump(mode="json")
    assert "source" not in dumped and "y_max" not in dumped
    assert ChartConfig.model_validate(dumped) == parsed  # nowy format czyta się sam


def full(**over):
    cfg = {
        "queries": [
            {"id": "A", "source": {"kind": "wan"}, "series": [{"key": "in_bps"}]},
            {"id": "B", "source": {"kind": "wan"}, "offset_min": 1440, "series": [{"key": "in_bps", "label": "Wczoraj"}]},
            {"id": "C", "source": {"kind": "device", "id": 1}, "series": [{"key": "cpu_percent", "axis": "right"}]},
        ],
        "stack": True,
        "axes": {"left": {"min": 0}, "right": {"min": 0, "max": 100, "label": "CPU"}},
        "thresholds": [{"value": 8e8, "color": 4}],
        "threshold_style": "line_area",
        "legend": {"mode": "table", "placement": "right", "values": ["last", "max", "max", "avg"]},
    }
    cfg.update(over)
    return cfg


def test_multi_source_chart_with_axes_thresholds_and_legend():
    parsed = ChartConfig.model_validate(full())
    assert [q.id for q in parsed.queries] == ["A", "B", "C"] and parsed.queries[1].offset_min == 1440
    assert parsed.queries[2].series[0].axis == "right" and parsed.axes.right.max == 100
    assert parsed.legend.values == ["last", "max", "avg"]  # bez powtórzeń
    DashboardLayout.model_validate(layout({"id": "c1", "type": "chart", "w": 6, "config": full()}))


@pytest.mark.parametrize(
    "over",
    [
        {"queries": []},
        {"queries": [{"id": "A", "source": {"kind": "wan"}, "series": [{"key": "in_bps"}]}] * 2},  # to samo id
        {"queries": [{"id": "a", "source": {"kind": "wan"}, "series": [{"key": "in_bps"}]}]},
        {"queries": [{"id": "A", "source": {"kind": "wan"}, "offset_min": 30, "series": [{"key": "in_bps"}]}]},
        {"queries": [{"id": "A", "source": {"kind": "wan"}, "series": [{"key": "in_bps", "axis": "top"}]}]},
        {"queries": [{"id": "A", "source": {"kind": "device", "id": 1}, "series": [{"key": "in_bps"}]}]},
        {"queries": [{"id": c, "source": {"kind": "wan"}, "series": [{"key": "in_bps"}, {"key": "out_bps"}]} for c in "ABCDEFG"]},
        {"queries": [{"id": c, "source": {"kind": "interface", "id": 1}, "series": [{"key": k} for k in ("in_bps", "out_bps", "in_errors")]} for c in "ABCDE"]},
        {"axes": {"left": {"min": 10, "max": 5}}},
        {"thresholds": [{"value": 1}] * 5},
        {"thresholds": [{"value": 1, "color": 9}]},
        {"threshold_style": "kropki"},
        {"legend": {"mode": "chmurka"}},
        {"legend": {"values": ["median"]}},
    ],
)
def test_rejects_invalid_multi_source_chart(over):
    with pytest.raises(ValidationError):
        ChartConfig.model_validate(full(**over))


# --- panele od 0.27.0 --------------------------------------------------------------------------------


def panel(type_, config):
    return layout({"id": "p1", "type": type_, "w": 4, "config": config})


def test_heatmap():
    cfg = {"source": {"kind": "wan"}, "key": "in_bps"}
    heat = DashboardLayout.model_validate(panel("heatmap", cfg)).widgets[0].config
    assert (heat.reduce, heat.group, heat.weeks, heat.color) == ("avg", "weekday", 4, 1)
    for bad in ({"key": "cpu_percent"}, {"weeks": 2}, {"group": "date", "weeks": 12}):
        with pytest.raises(ValidationError):
            DashboardLayout.model_validate(panel("heatmap", {**cfg, **bad}))


def test_pie():
    cpu = DashboardLayout.model_validate(panel("pie", {"device_id": 1, "metric": "cpu", "item": "/"})).widgets[0].config
    assert (cpu.limit, cpu.item, cpu.collection()) == (8, None, ("devices", None))  # dysk tylko dla „disk”
    disk = DashboardLayout.model_validate(panel("pie", {"device_id": 4, "metric": "disk", "item": "/srv"})).widgets[0].config
    assert (disk.item, disk.collection()) == ("/srv", ("disks", 4))
    # Cała sieć – bez urządzenia; WiFi i maszyny – urządzenie opcjonalne
    whole = DashboardLayout.model_validate(panel("pie", {"device_id": 3, "metric": "devices_state"})).widgets[0].config
    assert (whole.device_id, whole.collection()) == (None, ("devices", None))
    assert DashboardLayout.model_validate(panel("pie", {"metric": "wifi_clients"})).widgets[0].config.collection() == ("wifi", None)
    ports = DashboardLayout.model_validate(panel("pie", {"device_id": 2, "metric": "ports_in", "limit": 5})).widgets[0].config
    assert ports.collection() == ("ports", 2)
    port = DashboardLayout.model_validate(panel("pie", {"device_id": 2, "metric": "port_load", "item": "46"})).widgets[0].config
    assert (port.item, port.collection()) == ("46", ("ports", 2))
    for bad in ({"device_id": 2, "metric": "port_load"}, {"device_id": 2, "metric": "port_dir", "item": "/"}, {"metric": "ports_in"}, {"device_id": 1, "metric": "swap"}, {"device_id": 1, "metric": "cpu", "limit": 1}, {"device_id": 1, "metric": "cpu", "limit": 13}):
        with pytest.raises(ValidationError):
            DashboardLayout.model_validate(panel("pie", bad))


def test_chart_annotations():
    chart = {"queries": [{"id": "A", "source": {"kind": "wan"}, "series": [{"key": "in_bps"}]}]}
    assert DashboardLayout.model_validate(panel("chart", chart)).widgets[0].config.annotations == "auto"  # układy sprzed 0.34.0
    assert DashboardLayout.model_validate(panel("chart", {**chart, "annotations": "off"})).widgets[0].config.annotations == "off"
    with pytest.raises(ValidationError):
        DashboardLayout.model_validate(panel("chart", {**chart, "annotations": "some"}))


def test_stat_gauge_and_change():
    plain = DashboardLayout.model_validate(panel("stat", {"source": {"kind": "wan"}, "key": "in_bps"})).widgets[0].config
    assert (plain.display, plain.max, plain.show_change) == ("number", None, False)  # układy sprzed 0.33.0
    cfg = {"source": {"kind": "device", "id": 1}, "key": "cpu_percent", "display": "gauge", "max": 100, "show_change": True}
    gauge = DashboardLayout.model_validate(panel("stat", cfg)).widgets[0].config
    assert (gauge.display, gauge.max, gauge.show_change) == ("gauge", 100, True)
    for bad in ({"display": "pie"}, {"max": 0}):
        with pytest.raises(ValidationError):
            DashboardLayout.model_validate(panel("stat", {**cfg, **bad}))


def test_new_panels_validate():
    DashboardLayout.model_validate(panel("stat", {"source": {"kind": "wan"}, "key": "in_bps", "thresholds": [{"value": 5e8, "color": 5}]}))
    DashboardLayout.model_validate(panel("bargauge", {"collection": {"kind": "disks", "device_id": 3}, "key": "used_percent", "max": 100}))
    DashboardLayout.model_validate(panel("table", {"collection": {"kind": "ports", "device_id": 2}, "columns": ["up", "in_bps"], "sort_by": "in_bps", "sort_desc": True}))
    parsed = DashboardLayout.model_validate(panel("state_timeline", {"items": [{"kind": "device", "id": 1}, {"kind": "device", "id": 1}, {"kind": "interface", "id": 5, "device_id": 1}]}))
    assert [(i.kind, i.id) for i in parsed.widgets[0].config.items] == [("device", 1), ("interface", 5)]
    assert DashboardLayout.model_validate(panel("state_timeline", {})).widgets[0].config.items == []
    devices = DashboardLayout.model_validate(panel("table", {"collection": {"kind": "devices", "device_id": 9}, "columns": ["cpu_percent"]}))
    assert devices.widgets[0].config.collection.device_id is None


@pytest.mark.parametrize(
    ("type_", "config"),
    [
        ("stat", {"source": {"kind": "wan"}, "key": "cpu_percent"}),
        ("stat", {"source": {"kind": "wan"}, "key": "in_bps", "reduce": "median"}),
        ("bargauge", {"collection": {"kind": "disks"}, "key": "used_percent"}),  # brak urządzenia
        ("bargauge", {"collection": {"kind": "disks", "device_id": 1}, "key": "in_bps"}),
        ("bargauge", {"collection": {"kind": "disks", "device_id": 1}, "key": "used_percent", "min": 50, "max": 10}),
        ("bargauge", {"collection": {"kind": "ports", "device_id": 1}, "key": "in_bps", "limit": 0}),
        ("table", {"collection": {"kind": "ports", "device_id": 1}, "columns": []}),
        ("table", {"collection": {"kind": "ports", "device_id": 1}, "columns": ["up", "up"]}),
        ("table", {"collection": {"kind": "ports", "device_id": 1}, "columns": ["up"], "sort_by": "in_bps"}),
        ("table", {"collection": {"kind": "nieznane"}, "columns": ["up"]}),
        ("state_timeline", {"items": [{"kind": "vm", "id": 1}]}),
        ("state_timeline", {"items": [{"kind": "device", "id": i} for i in range(1, 22)]}),
    ],
)
def test_new_panels_reject_invalid(type_, config):
    with pytest.raises(ValidationError):
        DashboardLayout.model_validate(panel(type_, config))


# --- swobodna siatka i sekcje od 0.28.0 -----------------------------------------------------------


def test_free_grid_positions_and_sections():
    parsed = DashboardLayout.model_validate(
        layout(
            {"id": "s", "type": "section", "x": 0, "y": 0, "h": 1, "config": {"title": "  Sieć  ", "collapsed": True}},
            chart(w=5, x=0, y=1, h=8),
            {"id": "n", "type": "stat", "w": 7, "x": 5, "y": 1, "h": 4, "config": {"source": {"kind": "wan"}, "key": "in_bps"}},
        )
    )
    section, c, n = parsed.widgets
    assert (section.w, section.config.title, section.config.collapsed) == (12, "Sieć", True)
    assert (c.w, c.x, c.y, c.h) == (5, 0, 1, 8) and (n.x, n.w) == (5, 7)
    old = DashboardLayout.model_validate(layout(chart()))  # układ sprzed 0.28: bez pozycji
    assert (old.widgets[0].x, old.widgets[0].y, old.widgets[0].h) == (None, None, None)


@pytest.mark.parametrize(
    "widget",
    [
        chart(w=6, x=7),  # poza siatką
        chart(x=12),
        chart(h=0),
        chart(h=41),
        chart(y=-1),
        {"id": "s", "type": "section", "config": {"title": "   "}},
        {"id": "s", "type": "section", "config": {}},
    ],
)
def test_free_grid_rejects_invalid(widget):
    with pytest.raises(ValidationError):
        DashboardLayout.model_validate(layout(widget))


def test_chart_backup_link_color_option():
    """Od 0.55.0: odcinki ruchu przez łącze zapasowe innym kolorem – domyślnie wyłączone (stare pulpity bez zmian)."""
    base = {"source": {"kind": "wan"}, "series": [{"key": "in_bps"}]}
    assert ChartConfig.model_validate(base).wan_backup is False
    assert ChartConfig.model_validate({**base, "wan_backup": True}).wan_backup is True
