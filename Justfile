format:
	uv run ruff format .
	uv run ruff check . --fix

lint:
	uv run ruff check .

typecheck:
	uv run pyright

test:
	uv run pytest -m "not integration"

test-integration:
	uv run pytest -m integration

test-all: test test-integration

quality: format lint typecheck test-all

ci branch=`git branch --show-current`:
	gh workflow run CI --ref "{{branch}}"

ci-usage allowance="2000":
	@user="$(gh api user --jq .login)"; \
	if ! gh api -H "X-GitHub-Api-Version: 2026-03-10" "users/$user/settings/billing/usage" --jq '\
		[.usageItems[]? | select(.product == "actions" and .unitType == "Minutes")] as $items | \
		($items | map(.quantity) | add // 0) as $minutes | \
		($items | map(.grossAmount) | add // 0) as $gross | \
		($items | map(.discountAmount) | add // 0) as $discount | \
		($items | map(.netAmount) | add // 0) as $net | \
		"GitHub Actions usage for '"$user"'\nConfigured allowance: {{allowance}} minutes\nUsed Actions minutes: \($minutes)\nEstimated remaining minutes: \([({{allowance}} - $minutes), 0] | max)\nGross amount: $\($gross)\nDiscount amount: $\($discount)\nNet billed amount: $\($net)\n\nNote: Actions minutes are billable job-minutes. Matrix jobs count separately, and sub-minute jobs are rounded up to a minimum billable minute."'; then \
		printf '\nIf GitHub reported a missing scope, run:\n  gh auth refresh -h github.com -s user\n'; \
		exit 1; \
	fi
