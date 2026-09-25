"""Server-rendered, metadata-only operator dashboard."""

from collections.abc import Iterable
from html import escape

from regulated_ai.domain import OperatorTimeline

_DASHBOARD_HEADERS = {
    "Cache-Control": "no-store",
    "Content-Security-Policy": (
        "default-src 'none'; style-src 'self'; form-action 'self'; "
        "base-uri 'none'; frame-ancestors 'none'"
    ),
    "Permissions-Policy": "camera=(), geolocation=(), microphone=()",
    "Pragma": "no-cache",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
}


def dashboard_headers() -> dict[str, str]:
    """Return defensive response headers for operator HTML."""
    return dict(_DASHBOARD_HEADERS)


def render_operator_dashboard(
    timeline: OperatorTimeline | None = None,
    *,
    enforcement_id: str = "",
    error: str | None = None,
) -> str:
    """Render one escaped exact-ID timeline without client-side execution."""
    content = _empty_state(error) if timeline is None else _timeline(timeline)
    return f"""<!doctype html>
<html lang="pt-BR">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>RegulaAI · Painel operacional</title>
  <link rel="stylesheet" href="/operator/assets/dashboard.css?v=2">
</head>
<body>
  <header class="masthead">
    <div>
      <p class="eyebrow">RegulaAI</p>
      <h1>Painel operacional</h1>
      <p class="lede">
        Timeline somente leitura, com metadados e consulta por identificador exato.
      </p>
    </div>
  </header>
  <main>
    {_lookup_form(enforcement_id)}
    {content}
  </main>
  <footer>Sem payloads, argumentos, resultados, credenciais ou identidade do aprovador.</footer>
</body>
</html>
"""


def operator_dashboard_css() -> str:
    """Return the local stylesheet used by the no-script dashboard."""
    return _DASHBOARD_CSS


def _lookup_form(enforcement_id: str) -> str:
    return f"""
    <section class="lookup" aria-labelledby="lookup-title">
      <div>
        <p class="eyebrow">Consulta exata</p>
        <h2 id="lookup-title">Localizar enforcement</h2>
      </div>
      <form action="/operator" method="get">
        <label for="enforcement-id">Enforcement ID</label>
        <div class="form-row">
          <input id="enforcement-id" name="enforcement_id" value="{_text(enforcement_id)}"
                 pattern="[A-Za-z0-9][A-Za-z0-9._:@-]{{0,127}}" maxlength="128"
                 autocomplete="off" required>
          <button type="submit">Abrir timeline</button>
        </div>
      </form>
    </section>
    """


def _empty_state(error: str | None) -> str:
    if error == "not_found":
        title = "Timeline não encontrada"
        message = "Confirme o identificador exato e tente novamente."
    elif error == "unavailable":
        title = "Timeline indisponível"
        message = "Os metadados não puderam formar uma timeline íntegra."
    else:
        title = "Pronto para investigar"
        message = "Informe um enforcement ID. Esta tela não lista nem pesquisa registros."
    return f"""
    <section class="empty" aria-live="polite">
      <p class="eyebrow">Estado</p>
      <h2>{title}</h2>
      <p>{message}</p>
    </section>
    """


def _timeline(timeline: OperatorTimeline) -> str:
    decision = timeline.stages[0].status if timeline.stages else "UNKNOWN"
    enforcement_status = timeline.stages[1].status if len(timeline.stages) > 1 else "UNKNOWN"
    attention = "Atenção necessária" if timeline.attention_codes else "Sem atenção pendente"
    return f"""
    <section class="hero-status" aria-labelledby="timeline-title">
      <div>
        <p class="eyebrow">Enforcement</p>
        <h2 id="timeline-title">{_text(timeline.enforcement_id)}</h2>
        <p class="muted">
          Avaliação {_code(timeline.evaluation_id)} · Evidência {_code(timeline.evidence_id)}
        </p>
      </div>
      <div class="status-stack">
        {_pill(decision)}
        {_pill(enforcement_status)}
        <span class="pill {"warning" if timeline.attention_codes else "success"}">{attention}</span>
      </div>
    </section>
    {_summary(timeline)}
    {_attention(timeline)}
    {_stages(timeline)}
    {_lifecycle(timeline)}
    {_control_context(timeline)}
    {_provider_context(timeline)}
    {_transformations(timeline)}
    {_evidence_integrity(timeline)}
    """


def _summary(timeline: OperatorTimeline) -> str:
    approval = "registrada" if timeline.approval is not None else "não registrada"
    items = (
        ("Provider target", timeline.provider_target),
        ("Policy set", timeline.policy_set_version),
        ("Provider registry", timeline.provider_registry_version),
        ("Tool catalog", timeline.tool_catalog_version or "—"),
        ("Aprovação", approval),
        ("Histórico completo", _yes_no(timeline.history_complete)),
        ("Contexto do provedor completo", _yes_no(timeline.provider_context_complete)),
        ("Correlação", timeline.correlation_id),
    )
    cards = "".join(
        f'<div class="metric"><dt>{_text(label)}</dt><dd>{_text(value)}</dd></div>'
        for label, value in items
    )
    return (
        '<section aria-labelledby="summary-title">'
        '<h2 id="summary-title">Resumo</h2>'
        f'<dl class="metrics">{cards}</dl></section>'
    )


def _attention(timeline: OperatorTimeline) -> str:
    return _value_section(
        "attention-title",
        "Códigos de atenção",
        (item.value for item in timeline.attention_codes),
        empty="Nenhum código de atenção ativo.",
    )


def _stages(timeline: OperatorTimeline) -> str:
    rows = (
        (
            str(stage.sequence),
            stage.kind.value,
            stage.status,
            stage.record_id,
            stage.created_at.isoformat(),
            ", ".join(item.value for item in stage.attention_codes) or "—",
            "sim" if stage.approval_recorded else "não",
        )
        for stage in timeline.stages
    )
    return _table_section(
        "stages-title",
        "Estágios atuais",
        ("#", "Tipo", "Status", "Registro", "Criado em", "Atenção", "Aprovação"),
        rows,
    )


def _lifecycle(timeline: OperatorTimeline) -> str:
    rows = (
        (
            str(event.sequence),
            event.kind.value,
            event.status,
            event.source.value,
            event.recorded_at.isoformat(),
        )
        for event in timeline.lifecycle_events
    )
    note = (
        "Histórico completo para os registros correlacionados."
        if timeline.history_complete
        else "Histórico parcial ou migrado; não inferir transições ausentes."
    )
    return _table_section(
        "history-title",
        "Histórico append-only",
        ("Sequência", "Tipo", "Status", "Origem", "Registrado em"),
        rows,
        note=note,
    )


def _control_context(timeline: OperatorTimeline) -> str:
    return f"""
    <section aria-labelledby="controls-title">
      <h2 id="controls-title">Contexto de controle</h2>
      <div class="columns">
        {_value_block("Políticas", timeline.matched_policy_ids)}
        {_value_block("Objetivos de controle", timeline.control_objective_ids)}
        {_value_block("Obrigações", (item.value for item in timeline.obligation_types))}
        {_value_block("Classificações", (item.value for item in timeline.classification_labels))}
        {_value_block("Ferramentas autorizadas", timeline.authorized_tool_ids)}
        {_value_block("Razões da decisão", timeline.decision_reason_codes)}
        {_value_block("Razões do enforcement", timeline.enforcement_reason_codes)}
      </div>
    </section>
    """


def _provider_context(timeline: OperatorTimeline) -> str:
    rows = (
        (
            snapshot.capability_id,
            snapshot.provider_target,
            snapshot.state.value,
            ", ".join(snapshot.conditions) or "—",
            snapshot.verified_at.isoformat(),
            snapshot.registry_version,
            snapshot.record_version,
            " · ".join(snapshot.source_urls),
        )
        for snapshot in timeline.provider_capability_snapshots
    )
    note = (
        "Snapshots históricos completos para as capacidades registradas."
        if timeline.provider_context_complete
        else "Contexto legado incompleto; nenhuma proveniência foi reconstruída."
    )
    return _table_section(
        "provider-title",
        "Proveniência do provedor",
        (
            "Capacidade",
            "Target",
            "Estado",
            "Condições",
            "Verificado em",
            "Registry",
            "Record",
            "Fontes",
        ),
        rows,
        note=note,
    )


def _transformations(timeline: OperatorTimeline) -> str:
    rows = (
        (
            receipt.type.value,
            receipt.target,
            receipt.reason_code,
            receipt.receipt_id,
        )
        for receipt in timeline.transformation_receipts
    )
    return _table_section(
        "transformations-title",
        "Transformações",
        ("Tipo", "Campo", "Razão", "Receipt"),
        rows,
    )


def _evidence_integrity(timeline: OperatorTimeline) -> str:
    values = (
        ("Input digest", timeline.input_digest),
        ("Output digest", timeline.output_digest),
        ("Event digest", timeline.event_digest),
        ("Previous event digest", timeline.previous_event_digest or "—"),
    )
    rows = "".join(
        f'<tr><th scope="row">{_text(label)}</th><td>{_code(value)}</td></tr>'
        for label, value in values
    )
    return (
        '<section aria-labelledby="integrity-title">'
        '<h2 id="integrity-title">Integridade da evidência</h2>'
        f'<div class="table-wrap compact"><table><tbody>{rows}</tbody></table></div></section>'
    )


def _value_section(
    identifier: str,
    title: str,
    values: Iterable[str],
    *,
    empty: str,
) -> str:
    items = _value_list(values, empty=empty)
    return (
        f'<section aria-labelledby="{identifier}"><h2 id="{identifier}">'
        f"{_text(title)}</h2>{items}</section>"
    )


def _value_block(title: str, values: Iterable[str]) -> str:
    return f'<div class="value-block"><h3>{_text(title)}</h3>{_value_list(values)}</div>'


def _value_list(values: Iterable[str], *, empty: str = "Nenhum registro.") -> str:
    selected = tuple(values)
    if not selected:
        return f'<p class="muted">{_text(empty)}</p>'
    return "<ul>" + "".join(f"<li>{_code(value)}</li>" for value in selected) + "</ul>"


def _table_section(
    identifier: str,
    title: str,
    headers: tuple[str, ...],
    rows: Iterable[tuple[str, ...]],
    *,
    note: str | None = None,
) -> str:
    selected = tuple(rows)
    heading = "".join(f'<th scope="col">{_text(item)}</th>' for item in headers)
    body = (
        "".join(
            "<tr>" + "".join(f"<td>{_text(value)}</td>" for value in row) + "</tr>"
            for row in selected
        )
        if selected
        else f'<tr><td colspan="{len(headers)}" class="muted">Nenhum registro.</td></tr>'
    )
    note_html = "" if note is None else f'<p class="section-note">{_text(note)}</p>'
    return (
        f'<section aria-labelledby="{identifier}"><h2 id="{identifier}">{_text(title)}</h2>'
        f'{note_html}<div class="table-wrap"><table><thead><tr>{heading}</tr></thead>'
        f"<tbody>{body}</tbody></table></div></section>"
    )


def _pill(value: str) -> str:
    return f'<span class="pill">{_text(value)}</span>'


def _yes_no(value: bool) -> str:
    return "sim" if value else "não"


def _text(value: object) -> str:
    return escape(str(value), quote=True)


def _code(value: object) -> str:
    return f"<code>{_text(value)}</code>"


_DASHBOARD_CSS = """
:root {
  color-scheme: light;
  font-family: Inter, ui-sans-serif, system-ui, sans-serif;
  color: #14231d;
  background: #edf2ed;
}
* { box-sizing: border-box; }
body { margin: 0; min-height: 100vh; }
.masthead, main, footer { width: min(1180px, calc(100% - 32px)); margin-inline: auto; }
.masthead { padding: 48px 0 24px; }
h1, h2, h3, p { margin-top: 0; }
h1 { font-size: clamp(2rem, 5vw, 4.5rem); letter-spacing: -.055em; margin-bottom: 12px; }
h2 { font-size: 1.2rem; letter-spacing: -.02em; }
h3 { font-size: .9rem; color: #456055; }
.eyebrow {
  color: #0f7451;
  font-size: .72rem;
  font-weight: 800;
  letter-spacing: .16em;
  text-transform: uppercase;
  margin-bottom: 8px;
}
.lede, .muted, .section-note { color: #607168; }
main { display: grid; gap: 18px; padding-bottom: 36px; }
section {
  background: #fff;
  border: 1px solid #d3ddd6;
  border-radius: 16px;
  padding: 22px;
  box-shadow: 0 10px 30px rgba(22, 50, 37, .05);
  overflow: hidden;
}
.lookup, .hero-status {
  display: flex;
  gap: 24px;
  justify-content: space-between;
  align-items: end;
}
form { min-width: min(100%, 470px); }
label { display: block; font-size: .76rem; font-weight: 800; margin-bottom: 7px; }
.form-row { display: flex; gap: 8px; }
input {
  min-width: 0;
  flex: 1;
  border: 1px solid #aebdb4;
  border-radius: 9px;
  padding: 11px 12px;
  font: inherit;
}
input:focus { outline: 3px solid #bcebd7; border-color: #0f7451; }
button {
  border: 0;
  border-radius: 9px;
  padding: 11px 16px;
  background: #0c6748;
  color: #fff;
  font: inherit;
  font-weight: 800;
  cursor: pointer;
}
button:hover { background: #084f38; }
.status-stack { display: flex; flex-wrap: wrap; gap: 7px; justify-content: flex-end; }
.pill {
  display: inline-flex;
  border-radius: 999px;
  padding: 6px 10px;
  background: #e7eee9;
  color: #294138;
  font-size: .74rem;
  font-weight: 800;
}
.pill.success { background: #d7f4e6; color: #075d3c; }
.pill.warning { background: #fff0cc; color: #754d00; }
.metrics {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
  gap: 10px;
  margin: 0;
}
.metric { background: #f4f7f4; border-radius: 11px; padding: 13px; min-width: 0; }
.metric dt {
  color: #617168;
  font-size: .7rem;
  font-weight: 800;
  letter-spacing: .06em;
  text-transform: uppercase;
}
.metric dd { margin: 6px 0 0; overflow-wrap: anywhere; font-weight: 700; }
.columns { display: grid; grid-template-columns: repeat(auto-fit, minmax(230px, 1fr)); gap: 12px; }
.value-block { border-left: 3px solid #9ccab6; padding: 10px 12px; background: #f7faf8; }
ul { margin: 0; padding-left: 20px; }
li + li { margin-top: 6px; }
code {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: .79rem;
  overflow-wrap: anywhere;
}
.table-wrap { overflow-x: auto; }
.table-wrap:not(.compact) table { min-width: 1100px; }
table { width: 100%; border-collapse: collapse; font-size: .82rem; }
th, td {
  border-bottom: 1px solid #e0e7e2;
  padding: 10px 9px;
  text-align: left;
  vertical-align: top;
  overflow-wrap: anywhere;
}
th {
  color: #53675d;
  font-size: .7rem;
  letter-spacing: .05em;
  text-transform: uppercase;
  white-space: nowrap;
  overflow-wrap: normal;
}
.empty { min-height: 230px; display: grid; align-content: center; text-align: center; }
footer { color: #6a796f; font-size: .75rem; padding: 4px 0 38px; }
@media (max-width: 720px) {
  .lookup, .hero-status { align-items: stretch; flex-direction: column; }
  .status-stack { justify-content: flex-start; }
  .form-row { flex-direction: column; }
}
""".strip()
