from datetime import datetime

from jinja2 import Environment, select_autoescape

from worker.app import celery_app

_TEMPLATE = """<h1>{{ title }}</h1>
<p>Generado: {{ generated_at }}</p>
<table>
{% for item in opportunities %}
<tr>
  <td>{{ item.title }}</td>
  <td>{{ item.entity }}</td>
  <td>{{ item.country }}</td>
</tr>
{% endfor %}
</table>"""

_env = Environment(autoescape=select_autoescape(), trim_blocks=True, lstrip_blocks=True)


@celery_app.task(name="generate_report")
def generate_report(title: str, opportunities: list[dict[str, object]]) -> dict[str, object]:
    template = _env.from_string(_TEMPLATE)
    html = template.render(
        title=title,
        generated_at=datetime.utcnow().date(),
        opportunities=opportunities,
    )
    return {"title": title, "format": "html", "html_content": html}
