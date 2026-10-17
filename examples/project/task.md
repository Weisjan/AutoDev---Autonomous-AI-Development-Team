Build a small Python invoice repository using only the standard library.

Design three milestones and a task dependency graph:

1. Core: independent domain.py and formatting.py modules.
   - domain.subtotal(prices) sums integer cents, returns 0 for an empty list,
     and raises ValueError if any price is negative.
   - formatting.format_total(cents) returns dollars with two decimal places,
     for example 1234 becomes "$12.34".
2. Application: app.invoice_total(prices) composes both core modules and
   returns the formatted subtotal. It must depend on both core tasks.
3. Documentation: README.md describes these interfaces, examples and testing.
   This task depends on the application milestone.

Existing trusted tests are tests/test_domain.py, tests/test_formatting.py and
tests/test_app.py. They are protected and must not be rewritten. Use the first
two tests for their respective independent tasks; use test_app.py only once
both prerequisites are integrated. Run the complete suite at the end.

Do not introduce dependencies, installers, executable scripts, hidden files,
network services, or changes to project/control configuration.
