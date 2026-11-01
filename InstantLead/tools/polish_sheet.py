import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools.lib import sheet
from tools.lib.config import get_config

def main():
    cfg = get_config()
    service = sheet._service(cfg)
    titles = sheet.ensure_tabs(service, cfg)
    
    # 1. Remove stray value in G9 of Leads tab
    range_name = f"'{cfg.sheet_tab}'!G9"
    service.spreadsheets().values().update(
        spreadsheetId=cfg.sheet_id,
        range=range_name,
        valueInputOption="USER_ENTERED",
        body={"values": [[""]]}
    ).execute()
    print("Removed stray value in G9.")

    # 2. Force format tabs
    for tab, sheet_id in titles.items():
        headers = sheet.HEADERS if tab == cfg.sheet_tab or tab == cfg.quarantine_tab else sheet.DIGEST_HEADERS
        sheet._format_tab(service, cfg, tab, sheet_id, headers)
        print(f"Applied formatting to {tab}.")

if __name__ == "__main__":
    main()
