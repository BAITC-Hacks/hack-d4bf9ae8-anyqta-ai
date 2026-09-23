.PHONY: demo-up demo-down demo-logs demo-status demo-reset test acceptance evaluate container-check

demo-up:
	docker compose up --build -d

demo-down:
	docker compose down

demo-logs:
	docker compose logs --tail=100 career-quest

demo-status:
	docker compose ps

demo-reset:
	sh scripts/demo-reset.sh

test:
	python3 -m unittest discover -s backend/tests -v

acceptance:
	python3 scripts/acceptance.py

evaluate:
	python3 scripts/evaluate_recommendations.py

container-check:
	docker compose exec -T career-quest python -m unittest discover -s backend/tests -v
	docker compose exec -T career-quest python scripts/acceptance.py
	docker compose exec -T career-quest python scripts/evaluate_recommendations.py
