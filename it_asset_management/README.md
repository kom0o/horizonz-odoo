# IT Asset Management & Digital Custody (Odoo 18 Community)

A robust, enterprise-grade IT Asset Management and Digital Custody system designed specifically for **Odoo 18 Community Edition**. This module natively replaces and upgrades custom Studio implementations with clean, maintainable Python code, automated lifecycle transitions, bilingual PDF custody forms, and WhatsApp-driven approvals via **n8n**.

---

## 🌟 Key Features

1. **Hardware & Digital Asset Master (`it.asset`)**:
   - Comprehensive technical specifications: CPU, RAM, NVMe/SSD/HDD storage, Serial Number, Model & SKU.
   - Peripherals tracking (Keyboard, Mouse included).
   - Software and compliance auditing: OS, MS Office licenses, Antivirus status.
   - Financial & warranty tracking: Acquisition date, price in SAR, warranty coverage.
   - Interactive Kanban pipeline with stages: **Stock**, **Assigned**, **Scrap**, **Sold**.

2. **Custody Assignment & Handover (`it.asset.assign`)**:
   - Multi-device bundling: Laptop/PC, Secondary Monitor, Keyboard, Mouse, and Printer.
   - **Automated Reassignment Conflict Resolution**: Automatically detaches assets from previous holders when re-assigned.
   - **n8n & WhatsApp Digital Approvals**: Initiates webhook notification to n8n to send interactive WhatsApp acceptance messages to employees.
   - Generates official bilingual **IT Asset Issue Form (نموذج تسليم عهدة أجهزة تقنية)** PDF.

3. **Asset Return & Employee Clearance (`it.asset.return`)**:
   - Tracks return reasons (Resignation, Hardware Upgrade, Defective/Damaged, Project End).
   - **Automated Inventory Restoration**: Automatically resets asset stage back to **Stock** and clears active custodian upon return verification.
   - Generates official bilingual **IT Asset Return Form (نموذج استرجاع عهدة أجهزة تقنية / إخلاء طرف)** PDF.

4. **Decommissioning & Scrapping (`it.asset.disposal`)**:
   - Price-driven automated lifecycle:
     - **Price = 0 SAR** $\rightarrow$ Automatically transitions to **Scrap** (damage, theft, loss).
     - **Price > 0 SAR** $\rightarrow$ Automatically transitions to **Sold** with buyer tracking.

5. **IT Credentials Vault (`it.credential`)**:
   - Encrypted and masked storage for system logins, server IP/URLs, and administrative credentials.

6. **Physical Multi-Branch Locations (`it.asset.location`)**:
   - Track hardware across 40+ facilities, factories, stockyards, and head offices in Saudi Arabia.

---

## 📂 Module Structure

```text
it_asset_management/
├── __init__.py
├── __manifest__.py
├── controllers/
│   ├── __init__.py
│   └── main.py                     # Webhook endpoint for n8n WhatsApp confirmation
├── models/
│   ├── __init__.py
│   ├── it_asset.py                 # Core IT asset model
│   ├── it_asset_stage.py           # Pipeline stages (Stock, Assigned, Scrap, Sold)
│   ├── it_asset_location.py        # Physical branches & factory locations
│   ├── it_asset_assign.py          # Custody assignments & WhatsApp triggers
│   ├── it_asset_return.py          # Returns & inventory recovery
│   ├── it_asset_disposal.py        # Scrap and liquidation disposition
│   ├── it_credential.py            # Credentials vault
│   ├── res_partner.py              # Employee custody demographics
│   └── res_config_settings.py      # n8n webhook settings
├── security/
│   ├── it_asset_security.xml       # User & Manager access groups
│   └── ir.model.access.csv         # Complete ACL rules
├── data/
│   ├── ir_sequence_data.xml        # Auto-numbering (A0001, ASG-0001, RET-0001, DISP-0001)
│   ├── it_asset_stage_data.xml     # Default stages
│   └── it_asset_location_data.xml  # Seed branches across KSA
├── views/
│   ├── it_asset_views.xml          # Kanban, List, Form, Search
│   ├── it_asset_assign_views.xml   # Assignment forms & WhatsApp actions
│   ├── it_asset_return_views.xml   # Return forms & clearance
│   ├── it_asset_disposal_views.xml # Disposal views
│   ├── it_credential_views.xml     # Credentials vault views
│   ├── it_asset_stage_views.xml    # Stages setup
│   ├── it_asset_location_views.xml # Locations setup
│   ├── res_partner_views.xml       # Partner custody tab
│   ├── res_config_settings_views.xml
│   └── menus.xml                   # Root menu & submenus
├── report/
│   ├── it_asset_reports.xml        # Report action registrations
│   ├── it_asset_issue_report_template.xml  # Bilingual Issue Form QWeb
│   └── it_asset_return_report_template.xml # Bilingual Return Form QWeb
└── data_migration/
    ├── export_data_from_dump.py    # Utility to parse dump.sql
    └── exported_csv/               # Ready-to-import CSV files
```

---

## 🚀 Installation Guide (Odoo 18 Community)

1. Copy the `it_asset_management` directory into your Odoo `custom_addons` path.
2. Ensure dependencies are installed in your Python environment:
   ```bash
   pip install requests
   ```
3. Restart your Odoo service.
4. Activate Developer Mode in Odoo (`Settings` $\rightarrow$ `Activate the developer mode`).
5. Navigate to `Apps` $\rightarrow$ `Update Apps List`.
6. Search for `IT Asset Management` and click **Activate**.

---

## ⚡ WhatsApp & n8n Integration Setup

### 1. Configure Outgoing Webhook in Odoo
1. Go to `IT Assets` $\rightarrow$ `Configuration` $\rightarrow$ `Settings`.
2. Under **n8n & WhatsApp Digital Approvals**, configure your n8n Webhook URL:
   ```text
   https://n8n.srv1247626.hstgr.cloud/webhook/96e11f25-dc57-4043-b8af-0a502b8118e6
   ```

### 2. Outgoing Webhook Payload (Odoo $\rightarrow$ n8n)
When you click **"Send WhatsApp Confirmation"** on an assignment record, Odoo sends:
```json
{
  "record_id": 42,
  "assignment_ref": "ASG-0042",
  "assign_date": "2026-10-15",
  "employee": {
    "id": 150,
    "name": "Ahmed Al-Harbi",
    "arabic_name": "أحمد الحربي",
    "employee_code": "0042",
    "phone": "+966500000000",
    "department": "IT Operations"
  },
  "assets": [
    {
      "id": 596,
      "ref": "A0145",
      "name": "Laptop - A0145",
      "type": "laptop",
      "serial_no": "5CD451G0PL",
      "model_sku": "HP ProBook 450 G10",
      "cpu": "Intel Core i7 13th Gen",
      "ram": "16 GB DDR4"
    }
  ]
}
```

### 3. Incoming Confirmation Webhook (n8n $\rightarrow$ Odoo)
When the employee responds to WhatsApp with **Accept / تأكيد**, n8n issues an HTTP POST to:
```text
POST https://<your-odoo-domain>/api/it_asset/webhook/approve
Content-Type: application/json

{
  "jsonrpc": "2.0",
  "params": {
    "record_id": 42,
    "status": "approved",
    "token": "it_assets_secure_token"
  }
}
```
Odoo automatically:
- Confirms the custody assignment.
- Sets the assets' stages to **Assigned**.
- Updates the employee ownership.
- Logs the WhatsApp confirmation event in Chatter.

---

## 📦 Data Migration from Backup (`dump.sql`)

If you want to migrate existing data from your Studio dump:
1. Run the migration script inside `data_migration/`:
   ```bash
   python it_asset_management/data_migration/export_data_from_dump.py
   ```
2. The script extracts clean CSVs in `data_migration/exported_csv/`:
   - `it_asset_location.csv` (46 locations pre-mapped)
   - `it_asset.csv` (148 hardware assets with specs and serials)
   - `it_credential.csv`
3. Go to `IT Assets` $\rightarrow$ `Assets`, click the cog wheel $\rightarrow$ **Import Records**, and load `it_asset.csv`.
