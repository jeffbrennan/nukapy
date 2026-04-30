"""Hello-world: fetch 5 rows from NYC 311 Service Requests.

Copy .env.example to .env and set SOCRATA_APP_TOKEN to avoid rate limits.
"""

from nukapy import Socrata

client = Socrata("data.cityofnewyork.us")
rows = client.get("erm2-nwe9", limit=5)
for row in rows:
    print(row.get("unique_key"), row.get("complaint_type"), row.get("created_date"))
