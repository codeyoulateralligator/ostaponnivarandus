# Cashroll PDF Exporter Setup Tutorial

This guide shows how to create a clean Python virtual environment, install the required packages, and run `cashrollitegija.py`.

The script fetches note data directly from:

```text
http://hirve.myftp.org:7777/cashroll/db_get_table.php
```

and creates a PDF catalog in:

```text
cashroll_output/cashroll_catalog.pdf
```

---

## 1. Go to your project folder

```bash
cd ~/Devel/ostaponnivarandus
```

Or create a new folder:

```bash
mkdir -p ~/Devel/cashroll_pdf && cd ~/Devel/cashroll_pdf
```

---

## 2. Create a Python virtual environment

```bash
python3 -m venv .venv
```

---

## 3. Activate the virtual environment

```bash
source .venv/bin/activate
```

After activation, your terminal should show something like:

```text
(.venv) raigo@A224:~/Devel/cashroll_pdf$
```

---

## 4. Upgrade pip

```bash
python -m pip install --upgrade pip
```

---

## 5. Create `requirements.txt`

Create the file:

```bash
nano requirements.txt
```

Paste this:

```text
requests
pillow
reportlab
tqdm
```

Save and exit:

```text
CTRL+O
ENTER
CTRL+X
```

---

## 6. Install requirements

```bash
pip install -r requirements.txt
```

---

## 7. Add the script

Create the script file:

```bash
nano cashrollitegija.py
```

Paste the Python script into it, then save:

```text
CTRL+O
ENTER
CTRL+X
```

Make it executable:

```bash
chmod +x cashrollitegija.py
```

---

## 8. Add the missing-image placeholder

The script expects a placeholder image named:

```text
missing_note.png
```

Put your attached banknote placeholder image in the same folder as the script:

```text
cashrollitegija.py
missing_note.png
requirements.txt
```

Example folder layout:

```text
cashroll_pdf/
├── .venv/
├── cashrollitegija.py
├── missing_note.png
└── requirements.txt
```

The placeholder is used whenever a banknote has no front or back image.

---

## 9. Run a small test

Run only 16 notes first:

```bash
python cashrollitegija.py --limit 16
```

This should create:

```text
cashroll_output/cashroll_catalog.pdf
```

Open it:

```bash
xdg-open cashroll_output/cashroll_catalog.pdf
```

---

## 10. Run the full export

```bash
python cashrollitegija.py
```

Output files:

```text
cashroll_output/
├── cashroll_catalog.pdf
├── cashroll_data.json
├── debug/
└── images/
```

---

## 11. Useful commands

Run with a custom output PDF name:

```bash
python cashrollitegija.py --out my_cashroll_catalog.pdf
```

Run with fewer notes per page:

```bash
python cashrollitegija.py --per-page 6
```

Run without downloading images:

```bash
python cashrollitegija.py --no-images
```

Run with a larger delay between requests:

```bash
python cashrollitegija.py --delay 0.1
```

---

## 12. Deactivate the virtual environment

When finished:

```bash
deactivate
```

---

## 13. Reactivate later

Next time you return to the project:

```bash
cd ~/Devel/cashroll_pdf && source .venv/bin/activate
```

Then run:

```bash
python cashrollitegija.py
```

---

## Troubleshooting

### `ModuleNotFoundError: No module named 'requests'`

Your virtual environment is not active or requirements were not installed.

Fix:

```bash
source .venv/bin/activate && pip install -r requirements.txt
```

---

### `missing_note.png` warning

The placeholder file is missing.

Fix: put the banknote placeholder image next to the script and name it:

```text
missing_note.png
```

---

### PDF is old / unchanged

Delete old output and run again:

```bash
rm -rf cashroll_output && python cashrollitegija.py
```

---

### Check installed packages

```bash
pip list
```

---

### Save exact package versions

After everything works:

```bash
pip freeze > requirements.txt
```
