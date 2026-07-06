# Publishing to GitHub

This template is intended to be published without private local state.

## 1. Check What Git Would Publish

```powershell
git status --short
git status --ignored --short
```

Generated private state should appear only under ignored paths.

## 2. Verify Ignore Rules

```powershell
git check-ignore -v telos/telos.db
git check-ignore -v telos/radar/example.md
git check-ignore -v telos/memories/example.md
```

Each command should print a matching `.gitignore` rule.

## 3. Create a Public Repository

```powershell
git init
git add .
git commit -m "Initial public Telos Engine template"
git branch -M main
git remote add origin https://github.com/YOUR_USER/telos-engine.git
git push -u origin main
```

## 4. After You Start Using Telos

After `python telos.py init` or any radar run, check Git before committing:

```powershell
git status --short
```

If generated private files appear as untracked, fix `.gitignore` before pushing.
