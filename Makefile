# vps-runner Makefile - local operations (CI uses the GitHub workflows).

SHELL := /bin/bash
ROOT  ?= /opt/vps-runner

.PHONY: help deploy undeploy doctor logs status smoke

help:
	@echo "targets:"
	@echo "  deploy    install/update the stack locally (sudo, uses ./deploy)"
	@echo "  undeploy  cleanly remove the stack (add PURGE=1 to delete $(ROOT))"
	@echo "  doctor    run the health check locally"
	@echo "  logs      follow controller logs"
	@echo "  status    print controller status JSON"
	@echo "  smoke     run the autoscaler smoke tests (needs python3)"

deploy:
	sudo bash deploy/install.sh

undeploy:
	sudo bash deploy/uninstall.sh $(if $(PURGE),--purge,)

doctor:
	bash scripts/doctor.sh

logs:
	docker logs -f vps-runner-controller

status:
	curl -fsS http://127.0.0.1:8080/api/status | jq .

smoke:
	python3 scripts/smoke_autoscaler.py
