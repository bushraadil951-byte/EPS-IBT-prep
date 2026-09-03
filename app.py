{% extends 'base.html' %}
{% block title %}Import Results{% endblock %}
{% block page_title %}Import Results from CSV{% endblock %}
{% block back_button %}<a href="/admin" class="btn btn-secondary btn-sm">← Back</a>{% endblock %}

{% block content %}

<!-- Instructions -->
<div class="card" style="margin-bottom:20px;border-left:4px solid #6366f1">
  <h3 style="margin:0 0 10px;font-size:.95rem;color:#1e293b">📤 Import Google Form Results</h3>
  <p style="font-size:.83rem;color:#64748b;margin-bottom:12px">
    Upload a CSV file with student usernames and their answers (A/B/C/D) for each question.
    The system will calculate scores and save results as if students took the test on the portal.
  </p>
  <div style="background:#f8fafc;border-radius:8px;padding:12px;font-size:.8rem;color:#475569;font-family:monospace">
    username,q1,q2,q3,q4,q5,q6,q7,q8<br>
    ayesha_01,A,B,C,B,A,C,B,D<br>
    aynoor_02,A,A,C,B,B,C,A,D
  </div>
  <a href="/admin/download/results-template" style="display:inline-block;margin-top:12px;background:#6366f1;color:#fff;padding:7px 14px;border-radius:6px;text-decoration:none;font-size:.8rem;font-weight:600">
    ⬇ Download CSV Template
  </a>
</div>

<!-- Upload Form -->
<div class="card" style="margin-bottom:20px">
  <form method="POST" action="/admin/import-results" enctype="multipart/form-data">
    <input type="hidden" name="action" value="preview"/>
    <div style="display:flex;gap:12px;align-items:flex-end;flex-wrap:wrap">
      <div>
        <label style="font-size:.78rem;font-weight:600;display:block;margin-bottom:4px">Select Test</label>
        <select name="test_id" required style="padding:8px 12px;border:1px solid #e2e8f0;border-radius:8px;font-size:.83rem;min-width:220px">
          {% for t in tests %}
          <option value="{{ t.id }}" {{ 'selected' if test_id == t.id }}>{{ t.name }} ({{ t.grade }})</option>
          {% endfor %}
        </select>
      </div>
      <div style="flex:1">
        <label style="font-size:.78rem;font-weight:600;display:block;margin-bottom:4px">CSV File</label>
        <input type="file" name="csv_file" accept=".csv" required
               style="padding:7px;border:1px solid #e2e8f0;border-radius:8px;font-size:.82rem;width:100%"/>
      </div>
      <button type="submit" class="btn btn-primary">Preview Results →</button>
    </div>
  </form>
</div>

<!-- Errors -->
{% if errors %}
<div style="background:#fef2f2;border:1px solid #fecaca;border-radius:8px;padding:14px;margin-bottom:16px">
  <div style="font-weight:700;color:#991b1b;font-size:.83rem;margin-bottom:6px">⚠ Skipped rows:</div>
  {% for e in errors %}
  <div style="font-size:.78rem;color:#dc2626;">• {{ e }}</div>
  {% endfor %}
</div>
{% endif %}

<!-- Preview -->
{% if preview %}
<div class="card">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px">
    <h3 style="margin:0;font-size:.95rem">👁 Preview — {{ preview|length }} students</h3>
    <span style="font-size:.78rem;color:#64748b">Review before saving</span>
  </div>

  <div style="overflow-x:auto;margin-bottom:16px">
    <table class="data-table">
      <thead>
        <tr>
          <th>#</th><th>Name</th><th>Username</th>
          <th>Score</th><th>Percentage</th>
        </tr>
      </thead>
      <tbody>
        {% for r in preview %}
        <tr>
          <td>{{ loop.index }}</td>
          <td style="font-weight:600">{{ r.name }}</td>
          <td><code style="background:#f1f5f9;padding:2px 6px;border-radius:4px;font-size:.78rem">{{ r.username }}</code></td>
          <td>{{ r.score }} / {{ r.total }}</td>
          <td>
            <span style="font-weight:700;color:{{ '#16a34a' if r.percent >= 80 else '#f59e0b' if r.percent >= 60 else '#dc2626' }}">
              {{ r.percent }}%
            </span>
          </td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </div>

  <form method="POST" action="/admin/import-results">
    <input type="hidden" name="action" value="confirm"/>
    <input type="hidden" name="test_id" value="{{ test_id }}"/>
    {% for r in preview %}
    <input type="hidden" name="user_id" value="{{ r.user_id }}"/>
    <input type="hidden" name="score" value="{{ r.score }}"/>
    <input type="hidden" name="total" value="{{ r.total }}"/>
    <input type="hidden" name="percent" value="{{ r.percent }}"/>
    <input type="hidden" name="answers" value="{{ r.answers }}"/>
    <input type="hidden" name="section_scores" value="{{ r.section_scores }}"/>
    {% endfor %}
    <div style="display:flex;gap:10px">
      <button type="submit" class="btn btn-primary">✅ Confirm & Save {{ preview|length }} Results</button>
      <a href="/admin/import-results" class="btn btn-secondary">✖ Cancel</a>
    </div>
  </form>
</div>
{% endif %}
{% endblock %}
