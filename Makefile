.PHONY: demo-up demo-down demo-logs demo-status demo-reset test acceptance

demo-up:
	docker compose up --build -d

demo-down:
	docker compose down

demo-logs:
	docker compose logs --tail=100 career-quest

demo-status:
	docker compose ps

demo-reset:
	./scripts/demo-reset.sh

test:
	python3 -m unittest discover -s backend/tests -v

acceptance:
	python3 scripts/acceptance.py
