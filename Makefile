BINARY_NAME ?= cloudmanager
BUILD_TIME ?= $(shell date -u +'%Y-%m-%dT%H:%M:%SZ')

.PHONY: build clean run version web-build web-dev test ci test-release

build: web-build
	@build_version=$$(scripts/build-version) && \
	go build -trimpath -ldflags "-X main.Version=$$build_version -X main.BuildTime=$(BUILD_TIME)" -o $(BINARY_NAME) .

web-build:
	scripts/build-web

web-dev:
	cd web && npm ci && npm run dev

test-release:
	PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s scripts/tests -p 'test_*.py' -v

test: web-build test-release
	go mod verify
	go test ./...

ci: test build

version:
	@scripts/build-version

run: build
	./$(BINARY_NAME)

clean:
	rm -f $(BINARY_NAME)
