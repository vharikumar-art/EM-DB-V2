import io
import pandas as pd

df = pd.DataFrame({
    'Name': ['John'],
    'Email ': ['john@example.com'],
    'Citations': ['web']
})
file_bytes = io.BytesIO()
df.to_excel(file_bytes, index=False)
file_bytes.seek(0)

from app.utils.csv_utils import parse_file_bytes

try:
    res = parse_file_bytes(file_bytes.read(), "test.xlsx")
    print("Success. Columns:", res.columns.tolist())
except Exception as e:
    print("Error:", repr(e))
