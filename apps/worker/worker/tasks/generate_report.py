from datetime import datetime

from worker.app import celery_app


@celery_app.task(name="generate_report")
def generate_report(title: str, opportunities: list[dict[str, object]]) -> dict[str, object]:
    rows = "".join(
        f"<tr><td>{item.get('title')}</td><td>{item.get('entity')}</td><td>{item.get('country')}</td></tr>"
        for item in opportunities
    )
    html = f"<h1>{title}</h1><p>Generado: {datetime.utcnow().date()}</p><table>{rows}</table>"
    return {"title": title, "format": "html", "html_content": html}
