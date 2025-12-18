import os
import re
import pandas as pd
from tempfile import TemporaryDirectory
from typing import List

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# --- CORS Configuration ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

# --- USERS Database ---
users = {
    "aryan": "mypassword123",
    "admin": "adminpass"
}

# --------------------------
# LOGIN API
# --------------------------
@app.post("/api/login/")
async def login(user_id: str = Form(...), password: str = Form(...)):
    if user_id in users and users[user_id] == password:
        return {"status": "success", "message": "Login successful"}
    raise HTTPException(status_code=401, detail="Invalid credentials")


# --------------------------
# CORE EXCEL MERGE LOGIC
# --------------------------
def process_excels(paths: List[str]) -> pd.DataFrame | None:

    def get_header_row(df):
        for i, row in df.iterrows():
            if 'TIME' in row.astype(str).str.upper().values:
                return i
        return None

    def get_metadata(path):
        # ✅ UPDATED ENGINE TO 'openpyxl' for .xlsx support
        df_top = pd.read_excel(path, header=None, nrows=10, engine='xlrd')

        raw_date = str(df_top.iloc[1, 13]).replace("DATE:", "").strip()
        try:
            date_obj = pd.to_datetime(raw_date, dayfirst=True)
            date = date_obj.strftime("%d-%m-%Y")
        except:
            date = raw_date

        raw_shift = str(df_top.iloc[1, 19]).strip()
        shift_match = re.search(r"[ABC]", raw_shift.upper())
        shift = shift_match.group(0) if shift_match else ""

        raw_furnace = str(df_top.iloc[5, 1]).strip()
        furnace_match = re.search(r"[0-9]+", raw_furnace)
        furnace_col = f"F{furnace_match.group(0)}" if furnace_match else ""

        return date, shift, furnace_col

    all_data = []

    for path in paths:
        print("Processing:", path)
        try:
            df_raw = pd.read_excel(path, header=None, engine='xlrd')
            header_row = get_header_row(df_raw)
            if header_row is None:
                print(f"Skipping {path}: Header row with 'TIME' not found.")
                continue

            df = pd.read_excel(path, header=header_row, engine='xlrd')

            date, shift, furnace_label = get_metadata(path)

            mask = df.get("TIME").notna() if "TIME" in df.columns else df.index
            df.loc[mask, "Date"] = date
            df.loc[mask, "Shift"] = shift
            df.loc[mask, "Furnace"] = furnace_label

            # --- ORIGINAL FURNACE CYCLING LOGIC KEPT ---
            furnace_number = int(furnace_label.replace("F", "")) if furnace_label and furnace_label.startswith("F") and furnace_label[1:].isdigit() else 1
            pattern_counter = 0

            for i in range(len(df)):
                val = df.loc[i, "Furnace"] if "Furnace" in df.columns else ""
                is_blank = pd.isna(val) or str(val).strip() == ""

                if pattern_counter == 0:
                    pattern_counter = 1 if not is_blank else 0
                elif pattern_counter == 1:
                    pattern_counter = 2 if is_blank else 1
                elif pattern_counter == 2:
                    pattern_counter = 3 if not is_blank else 1
                elif pattern_counter == 3:
                    if is_blank:
                        furnace_number += 1
                        if furnace_number > 9:
                            furnace_number = 1
                    pattern_counter = 0

                if not is_blank and "Furnace" in df.columns:
                    df.loc[i, "Furnace"] = f"F{furnace_number}"

            all_data.append(df)

        except Exception as e:
            print(f"Error processing file {path}: {e}")
            continue

    if not all_data:
        return None

    merged_df = pd.concat(all_data, ignore_index=True)
    merged_df = merged_df.loc[:, ~merged_df.columns.str.contains("^Unnamed")]
    merged_df = merged_df.dropna(axis=1, how="all")

    if len(merged_df.columns) >= 3:
        last_three = merged_df.columns[-3:].tolist()
        other_cols = merged_df.columns[:-3].tolist()
        merged_df = merged_df[last_three + other_cols]

    empty_rows = merged_df[merged_df.isna().all(axis=1)].index.tolist()
    rows_to_delete = []

    for idx in empty_rows:
        rows_to_delete.extend([idx, idx + 1, idx + 2, idx + 3])

    rows_to_delete = sorted(set(i for i in rows_to_delete if i < len(merged_df)))
    merged_df = merged_df.drop(rows_to_delete).reset_index(drop=True)

    return merged_df


# --------------------------
# UPLOAD API
# --------------------------
@app.post("/api/upload/")
async def upload(files: List[UploadFile] = File(...)):
    if not files:
        raise HTTPException(400, detail="No files uploaded")

    with TemporaryDirectory() as tmp:
        paths = []
        for f in files:
            path = os.path.join(tmp, f.filename)
            with open(path, "wb") as w:
                w.write(await f.read())
            paths.append(path)

        result_df = process_excels(paths)
        if result_df is None:
            raise HTTPException(400, detail="Error: No valid data found in uploaded Excel files.")

        output = os.path.join(tmp, "Merged_Furnaces.xlsx")
        result_df.to_excel(output, index=False)

        return FileResponse(
            output,
            filename="Merged_Furnaces.xlsx",
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )


# --------------------------
# RUN SERVER
# --------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("backend:app", host="127.0.0.1", port=8000, reload=True)
    
    from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # allow all origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

    
@app.get("/")
async def root():
    return {"message": "Backend is running", "routes": ["/api/login/", "/api/upload/"]}


@app.get("/api/login/")
async def login_get():
    return {"message": "Use POST method for login"}
    
@app.get("/api/upload/")
async def upload_get():
    return {"message": "Use POST method to upload Excel files"}
