# Ostaponn ca$hroll helper
<img width="1672" height="941" alt="ostaponn_money" src="https://github.com/user-attachments/assets/66e4f34b-0eb4-4311-ba84-867e5e2a89ab" />
<img width="1672" height="941" alt="ostaponn_back" src="https://github.com/user-attachments/assets/a4fa1774-6fa4-4316-a842-1b47916eefab" />

This project creates a PDF catalog from the ca$hroll banknote collection site.

It can:

- log in to the site
- fetch the full collection table from `db_get_table.php`
- download front/back note images
- calculate and display currency value where available
- read logged-in item price and shipping fields
- create a portrait A4 PDF catalog
- add a styled title page using a premade Ostaponn money image
- print colorful console inventory statistics
- show the top most expensive notes by raw price

---

## 1. Project files

Recommended folder layout:

```text
cashroll_project/
├── cashrollitegija.py
├── cashroll_requirements.txt
├── missing_note.png
├── ostaponn_money.png
└── cashroll_output/
```

Required files:

```text
cashrollitegija.py
cashroll_requirements.txt
```

Optional but recommended files:

```text
missing_note.png
ostaponn_money.png
```

`missing_note.png` is used when a banknote image is missing.

`ostaponn_money.png` is used as the premade title-page money image.

You can also pass a custom title image with:

```bash
python3 cashrollitegija.py --title-money-image "ostaponn.png"
```

---

## 2. Create a Python virtual environment

From your project folder:

```bash
python3 -m venv .venv
```

Activate it:

```bash
source .venv/bin/activate
```

Upgrade pip:

```bash
python -m pip install --upgrade pip
```

---

## 3. Install requirements

```bash
pip install -r cashroll_requirements.txt
```

The latest requirements are:

```text
requests>=2.31.0
curl_cffi>=0.7.0
beautifulsoup4>=4.12.0
Pillow>=10.0.0
reportlab>=4.0.0
tqdm>=4.66.0
rich>=13.7.0
matplotlib>=3.7.0
```

---

## 4. Run a small test

With login:

```bash
python3 cashrollitegija.py --user xxx --password xxx --limit 10
```

Safer password prompt:

```bash
python3 cashrollitegija.py --user xxx --password-stdin --limit 10
```

With the premade title-page money image:

```bash
python3 cashrollitegija.py --user xxx --password xxx --limit 10 --title-money-image "ostaponn_money.png"
```

Without value/cost debug spam:

```bash
python3 cashrollitegija.py --user xxx --password xxx --limit 10 --no-value-debug --no-cost-debug
```

---

## 5. Full export

```bash
python3 cashrollitegija.py --user xxx --password xxx --title-money-image "ostaponn_money.png" --no-value-debug --no-cost-debug
```

Safer password prompt:

```bash
python3 cashrollitegija.py --user xxx --password-stdin --title-money-image "ostaponn_money.png" --no-value-debug --no-cost-debug
```

---

## 6. Output files

The script creates:

```text
cashroll_output/
├── cashroll_catalog.pdf
├── cashroll_data.json
├── debug/
└── images/
```

Main output:

```text
cashroll_output/cashroll_catalog.pdf
```

Open it on Linux:

```bash
xdg-open cashroll_output/cashroll_catalog.pdf
```

---

## 7. Command-line options

### Output path

```bash
python3 cashrollitegija.py --out my_catalog.pdf
```

### Limit number of rows

```bash
python3 cashrollitegija.py --limit 20
```

Useful for testing.

### Items per PDF page

Default is 8.

```bash
python3 cashrollitegija.py --per-page 8
```

### Disable note image downloading

```bash
python3 cashrollitegija.py --no-images
```

### Delay between rows

Default is `0.03`.

```bash
python3 cashrollitegija.py --delay 0.1
```

### Login

```bash
python3 cashrollitegija.py --user USERNAME --password PASSWORD
```

Safer:

```bash
python3 cashrollitegija.py --user USERNAME --password-stdin
```

### Disable debug output

```bash
python3 cashrollitegija.py --no-value-debug --no-cost-debug
```

### Top expensive notes count

Default is 100.

```bash
python3 cashrollitegija.py --top 25
```

### Title page money image

Default search order:

```text
ostaponn_money.png
ostaponn(1).png
ostaponn.png
```

Explicit:

```bash
python3 cashrollitegija.py --title-money-image "ostaponn_money.png"
```

---

## 8. Login and price fields

When logged in, the table has extra fields:

```text
row[16] = raw item price
row[17] = shipping
```

The script adds this to each PDF item description:

```text
Cost: item price + shipping = total
```

It also prints inventory stats at the end:

```text
Total notes processed
Notes with raw price
Notes missing raw price
Total inventory value, raw price only
Total shipping value
Total including shipping
Average raw price
Most expensive note
Cheapest priced note
Top N most expensive notes
```

---

## 9. Troubleshooting

### `ModuleNotFoundError`

Activate the virtual environment and reinstall:

```bash
source .venv/bin/activate && pip install -r requirements.txt
```

### Missing title image warning

Save the premade money image as:

```text
ostaponn_money.png
```

or run with:

```bash
python3 cashrollitegija.py --title-money-image "your_file.png"
```

### Missing placeholder warning

Save a placeholder banknote image as:

```text
missing_note.png
```

### Price/shipping not visible

Make sure you are logged in.

The script should print:

```text
Logged-in price/shipping columns appear to exist: row[16], row[17]
```

If it prints that price/shipping columns are not visible, login probably failed.

### Rebuild output from scratch

```bash
rm -rf cashroll_output && python3 cashrollitegija.py --user xxx --password-stdin --title-money-image "ostaponn_money.png" --no-value-debug --no-cost-debug
```

---

## 10. Freeze exact versions after it works

```bash
pip freeze > requirements_locked.txt
```

Use `requirements_locked.txt` only if you want exact package versions from your current machine.
