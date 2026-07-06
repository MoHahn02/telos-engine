# Privacy and Publishing

Telos is designed to create private local state.

Do not publish:

- `telos/telos.db`
- `telos/memories/`
- `telos/claims/`
- `telos/beliefs/`
- `telos/reviews/`
- `telos/radar/`
- `telos/finance/`
- `telos/geopolitics/`
- `telos/markets/`
- `telos/worldview/`
- `telos/personal/`
- `telos/dreams/`
- logs, caches or generated dossiers

The public template `.gitignore` blocks those paths by default.

Before pushing a public repository:

```powershell
git status --short
git ls-files telos
```

Expected tracked Telos files are limited to public static assets such as:

```text
telos/dashboard/index.html
```

If your generated reports appear in `git status`, stop and fix `.gitignore`.
