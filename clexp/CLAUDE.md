# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Context

This is a personal sandbox environment running in WSL on a private laptop. The owner is an experienced programmer, architect, and manager with a strategic/M&A background working in a **highly regulated banking environment**. The primary goal is to experiment here and then port solutions into that regulated environment with minimal friction.

## Environment

- **Sandbox**: WSL (Windows Subsystem for Linux) on a personal laptop
- **Docker**: Available in WSL. All Docker container/image names must be prefixed with `CL42_`
- **Primary language**: Python preferred for simplicity, but other languages are fine — explain them clearly
- **Regulated target**: Solutions need a clear migration path to a restricted banking environment (air-gapped or heavily firewalled, limited container access)

## Key Design Constraint: Sandbox → Bank

When proposing solutions, always consider the regulated banking environment migration path:

- Prefer self-contained solutions with minimal external dependencies
- Avoid solutions that rely on unrestricted internet access at runtime
- Prefer standard, auditable open-source libraries over niche ones
- When using Docker, use `CL42_` prefix on all container/image names
- Flag anything that would be blocked in a typical bank environment (outbound calls, OAuth flows, cloud-native services, etc.)
- Infrastructure-as-code (IaC) is acceptable and encouraged

## Docker usage

```bash
# Build with required prefix
docker build -t CL42_myapp .

# Run with required prefix
docker run --name CL42_myapp_instance CL42_myapp
```
