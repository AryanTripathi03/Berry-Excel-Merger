import os
import re
import pandas as pd
import tempfile
from typing import List


from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()





# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

# USERS
users = {
    "aryan": "mypassword123",
    "admin": "adminpass"
}

# SAFE EXCEL READER
def safe_read_excel(path, header=None):
    ext = path.lower().split(".")[-1]
    if ext == "xls":
        return pd.read_excel(path, header=header, engine="xlrd")
    else:
        return pd.read_excel(path, header=header, engine="openpyxl")


# LOGIN
@app.post("/api/login/")
async def login(user_id: str = Form(...), password: str = Form(...)):
    if user_id in users and users[user_id] == password:
        return {"status": "success", "message": "Login successful"}
    raise HTTPException(status_code=401, detail="Invalid credentials")


# MAIN EXCEL MERGE FUNCTION (unchanged)
from typing import Optional

def process_excels(paths: List[str]) -> Optional[pd.DataFrame]:

    
    def get_header_row(df):
        for i, row in df.iterrows():
            if 'TIME' in row.astype(str).str.upper().values:
                return i
        return None

    def get_metadata(path):
        df_top = safe_read_excel(path, header=None).head(10)
        raw_date = str(df_top.iloc[1, 13]).replace("DATE:", "").strip()
        try:
            date = pd.to_datetime(raw_date, dayfirst=True).strftime("%d-%m-%Y")
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
        try:
            df_raw = safe_read_excel(path, header=None)
            header_row = get_header_row(df_raw)
            if header_row is None:
                continue

            df = safe_read_excel(path, header=header_row)

            date, shift, furnace_label = get_metadata(path)

            mask = df["TIME"].notna()
            df.loc[mask, "Date"] = date
            df.loc[mask, "Shift"] = shift
            df.loc[mask, "Furnace"] = furnace_label

            # --------------- UPDATED FURNACE CYCLING LOGIC ---------------
            furnace_number = int(furnace_label.replace("F", "")) if furnace_label[1:].isdigit() else 1
            pattern_counter = 0

            for i in range(len(df)):
                val = df.loc[i, "Furnace"]
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

                if not is_blank:
                    df.loc[i, "Furnace"] = f"F{furnace_number}"

            all_data.append(df)

        except Exception as e:
            print("Error:", e)
            continue

    if not all_data:
        return None

    merged_df = pd.concat(all_data, ignore_index=True)
    merged_df = merged_df.loc[:, ~merged_df.columns.str.contains("^Unnamed")]
    merged_df = merged_df.dropna(axis=1, how="all")

    # ======== DELETE FULLY-EMPTY ROW + NEXT 3 ROWS ========
    delete_indices = []
    i = 0
    while i < len(merged_df):
        if merged_df.iloc[i].isna().all():
            delete_indices.extend(range(i, min(i + 4, len(merged_df))))
            i += 4
        else:
            i += 1

    merged_df = merged_df.drop(delete_indices, errors='ignore').reset_index(drop=True)

    # ======== MOVE Date / Shift / Furnace TO COLUMNS A / B / C ========
    desired_order = ["Date", "Shift", "Furnace"]
    remaining = [c for c in merged_df.columns if c not in desired_order]
    merged_df = merged_df[desired_order + remaining]

    return merged_df

# FIXED UPLOAD ROUTE
@app.post("/api/upload/")
async def upload(files: List[UploadFile] = File(...)):
    if not files:
        raise HTTPException(status_code=400, detail="No files uploaded")

    tmp = tempfile.gettempdir()
    saved_paths = []

    for f in files:
        file_path = os.path.join(tmp, f.filename)
        with open(file_path, "wb") as buffer:
            buffer.write(await f.read())
        saved_paths.append(file_path)

    result_df = process_excels(saved_paths)

    if result_df is None:
        raise HTTPException(status_code=400, detail="No valid data found in uploaded Excel files")

    output = os.path.join(tmp, "Merged_Furnaces.xlsx")
    result_df.to_excel(output, index=False)

    return FileResponse(
        output,
        filename="Merged_Furnaces.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


# ROOT
@app.get("/")
async def root():
    return {"message": "Backend is running",
            "routes": ["/api/login/", "/api/upload/"]}
    
    
    
import os
from fastapi import FastAPI


# your routes above

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run("backend:app", host="0.0.0.0", port=port)
    
