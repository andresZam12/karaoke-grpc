.PHONY: proto server test

proto:
	python -m grpc_tools.protoc -I proto --python_out=generated --grpc_python_out=generated proto/karaoke.proto

server:
	python -m server.main

test:
	pytest -v
