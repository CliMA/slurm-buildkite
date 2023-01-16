export JULIA_DEPOT_PATH := $(shell pwd)/.depot

.PHONY: all
all: .instantiate

${JULIA_DEPOT_PATH}:
	mkdir -p $@

.instantiate: Manifest.toml ${JULIA_DEPOT_PATH}
	julia --project -e 'using Pkg; Pkg.instantiate()'
	touch $@
