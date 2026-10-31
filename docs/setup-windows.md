# Windows setup (PowerShell)

The README quick start uses Mac/Linux commands. These are the Windows PowerShell equivalents, tested on Windows 11 with VS Code and Docker Desktop.

## 1. Show full file names

In File Explorer, turn on **View > Show > File name extensions**. Otherwise `.env.example` shows as `.env` and `README.md` as `README`, which makes it easy to edit the wrong file.

## 2. Python environment

Open the repo folder in VS Code, then **Terminal > New Terminal** (PowerShell).

```powershell
python -m venv .venv               # README: python3 -m venv .venv
.\.venv\Scripts\Activate.ps1       # README: source .venv/bin/activate
```

- If `python` is not found, use `py -m venv .venv`.
- If activation says "running scripts is disabled", run `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned` once, then activate again.
- The prompt starts with `(.venv)` when the environment is on. Repeat the activate line in every new terminal.
- Windows PowerShell 5.1 does not accept `&&`, so run the README's one-liner as two separate lines.

## 3. API key file

```powershell
Copy-Item .env.example .env        # README: cp .env.example .env
code .env                          # paste the team key, save
git check-ignore .env              # must print: .env
```

Never commit `.env`. If `git check-ignore` prints nothing, stop and tell the team.

## 4. Client data

Unzip the NTULearn package and copy its `docs`, `images`, `logs`, `sql` and `tabular` folders into the repo's `data\` folder, next to `data\README.md`.

Check: `data\sql\jurongmarine_cmms.sql` exists, and GitHub Desktop (or `git status`) still shows no changes under `data/`. If anything under `data/` appears as a change, do not commit.

## 5. Database

Start Docker Desktop first.

```powershell
docker compose up -d
cmd /c "docker compose exec -T mysql mysql -uroot -pcapstone < data\sql\jurongmarine_cmms.sql"
docker compose exec mysql mysql -uroot -pcapstone -e "SHOW DATABASES;"
```

PowerShell has no `<` redirect, so the import runs through `cmd /c`. Piping with `Get-Content` can mangle non-English characters, so avoid it. MySQL Workbench (Server > Data Import) also works.

## 6. Before every commit

- Pull first (GitHub Desktop: **Fetch origin**, then **Pull origin**).
- The Changes list must not contain `.env`, `.venv/`, or anything under `data/`.
- Pair work: add `Co-authored-by: Name <email>` to the commit description.
