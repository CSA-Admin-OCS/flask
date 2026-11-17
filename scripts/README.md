# scripts/

This file lists the **access-control (RBAC) scripts**: what each one is, why it exists, and when to run it. The older
`verify_*.py` and `db_*.py` scripts are not listed here yet; each has its purpose in the docstring at the top of the file.

None of these scripts is part of the running app, and nothing in the app imports them. Run each from the repo root.

- The scripts that call routes (`rbac_prober.py`, and anything that runs it) do it on a throwaway copy of the app: a copy of
  the tracked files, a clean environment with no provider keys, no network, and fresh throwaway data for every call. They
  cannot change your database or your files, and they cannot spend a provider's credit.
- `rbac_inventory.py` calls no route. It loads the app the way starting it does, which can create the app's usual empty
  `instance/` files if they are missing.
- The `verify_*.py` scripts that need accounts use a throwaway SQLite database and leave yours alone.

## How they fit together

```
rbac_inventory.py   what the code says guards each route ----+
                                                             +--> rbac_reconcile.py --> where they differ
rbac_prober.py      what each route really answers ----------+                |
                                                                              v
model/dataconfigs/permissions.json   a policy built from that (added by the next change)
```

Reports from `rbac_inventory.py`, `rbac_prober.py` and `rbac_reconcile.py` show which routes are open, so write them
outside the repo with `--out` and do not commit or post them. With no `--out` they print counts only.

## The scripts

| Script | What it does | Why it exists | When to run | Takes |
|---|---|---|---|---|
| `rbac_inventory.py` | Lists every route and what the code says guards it: the decorators, the role list the running app holds, what the function itself checks about the caller. Reads only; never calls a route. | Nobody can see the guards of all 250 method-and-route pairs at once. This is the written side of the evidence. | To see how every route is guarded, after adding or changing routes, and as input to `rbac_reconcile.py`. | 3 s |
| `rbac_fixture_app.py` | A tiny app with one route for each way this project guards (or fails to guard) a route. | Gives `verify_rbac_inventory.py` known answers to check the inventory against. | Never on its own. | n/a |
| `verify_rbac_inventory.py` | Checks that the inventory reads every fixture route correctly, gives the same answer twice, and can inventory this project. | So the inventory can be trusted. | After changing `rbac_inventory.py`, or the shape of `auth_required` / `token_required`. | 2 s |
| `rbac_prober.py` | Calls every route as nine kinds of caller (anonymous, invalid token, guest, user, mentor, teacher, admin, inactive mentor, expired guest) and records the status, any redirect, whether canary data came back, and whether the call wrote. | The code can only suggest who gets in: a check inside a function, a hook or an error can make the answer differ. This is what the app really does. | Before changing who may do what, and as input to `rbac_reconcile.py`. `--only TEXT` limits it to some routes and `--callers a,b` to some callers. | 55 s for both modes |
| `rbac_probe_fixture.py` | A tiny app with one route for each case the prober must get right: open, refused, leaking, writing, crashing, trying the network, hanging. | Gives `verify_rbac_prober.py` known answers. | Never on its own. | n/a |
| `verify_rbac_prober.py` | Checks every prober record against what the fixture route does, and each safety rule: clean environment, network off, fresh data, inert code payload, nothing written to the repo. | So the prober can be trusted, and so running it is known to be safe. | After changing `rbac_prober.py`. | 24 s |
| `rbac_reconcile.py` | Joins the inventory and the prober results and names each way the answers differ from the guard: a caller the guard should refuse who got in, a check inside the code, a route that fails only for anonymous callers, and so on. `--sample` also checks the reading against 40 hand-labelled routes. | One kind of evidence can be wrong; the two together show which routes need a person to look. | When you want that comparison, for example before changing a route's guard. It runs both tools itself unless given saved reports with `--inventory` and `--probe`. | 1 min (0 s from saved reports) |
| `rbac_sample_labels.py` | 40 routes labelled by a person reading each handler, drawn from every kind of guard. Data, not a program. | A tool checked only against itself proves nothing; this is the person's answer. | Never on its own. Edit it only when a labelled route's guard really changes. | n/a |
| `verify_rbac_reconcile.py` | Checks each comparison rule on small records written for it, then runs the tools on this project against the 40 labelled routes. | So the comparison can be trusted. | After changing `rbac_reconcile.py` or `rbac_inventory.py`. | 65 s |
