# Review checklist — Django / DRF

Put a copy at `<repo>/.claude/review-checklist.md`; the Codex `delivery-reviewer` skill
applies it after the task-correctness check.

## ORM

- N+1 queries; queries inside loops; repeated identical queries
- missing `select_related()` / `prefetch_related()`
- `SerializerMethodField` methods that hit the database
- full model loads where `values()`, `values_list()` or `exists()` would do
- `.count() > 0` instead of `.exists()`; `len(queryset)` instead of `.count()`
- `.save()` in a loop where `bulk_create()` / `bulk_update()` fits
- `try: Model.objects.get(...) except DoesNotExist` where `.filter(...).first()` is
  enough (not when `get()` semantics are required)

## Transactions and concurrency

- several related writes without `transaction.atomic()`
- read-modify-write without locking; missing `select_for_update()`
- non-idempotent operations that can run twice (retries, double submit)

## DRF

- new endpoints return DRF `Response`, not `JsonResponse`
- correct status codes; existing response shapes preserved unless the task changes them

## Forms and admin

- `cleaned_data[name]` inside `clean()` — a field that failed validation is missing
  there, so it raises `KeyError` (a 500) instead of a form error; expect `.get()`
- a foreign key in `list_display` without `list_select_related`
- inlines showing relation columns without `select_related` in `get_queryset`

## Migrations

- backward compatibility; nullable/default handling
- data migration safety; no explicit `id=` in data migrations (breaks the PG sequence)
- migrations that lock or rewrite large tables without need
