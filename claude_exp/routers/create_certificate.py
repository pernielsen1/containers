#!/usr/bin/env python3
import argparse
from datetime import datetime, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


DEFAULT_CERTS = [
    ("crypto_host", "crypto_host"),
    ("downstream", "downstream_host"),
    ("upstream_router_1", "upstream_router_1"),
    ("upstream_router_2", "upstream_router_2"),
    ("upstream_router_y_3", "upstream_router_y_3"),
]

DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "router_py" / "certs"


def create_self_signed_cert(prefix: Path, common_name: str):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, common_name),
    ])
    now = datetime.utcnow()
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=3650))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.SubjectAlternativeName([
                x509.DNSName(common_name),
                x509.DNSName("localhost"),
            ]),
            critical=False,
        )
        .add_extension(x509.KeyUsage(
            digital_signature=True,
            key_encipherment=True,
            content_commitment=False,
            data_encipherment=False,
            key_agreement=False,
            key_cert_sign=True,
            crl_sign=True,
            encipher_only=False,
            decipher_only=False,
        ), critical=True)
        .sign(key, hashes.SHA256())
    )

    cert_path = prefix.with_name(f"{prefix.name}_cert.pem")
    key_path = prefix.with_name(f"{prefix.name}_key.pem")
    ca_path = prefix.with_name(f"{prefix.name}_ca.pem")

    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    ca_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return cert_path, key_path, ca_path


def main():
    parser = argparse.ArgumentParser(description="Create self-signed certs for router SSL testing.")
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory to place generated certificate files (default: routers/router_py/certs, "
        "the shared dir every router_py/simulators/upstream_host config points at)",
    )
    parser.add_argument("--ssl-active", choices=["true", "false"], default="false")
    args = parser.parse_args()

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    for role, common_name in DEFAULT_CERTS:
        prefix = out_dir / f"{role}_ssl_active_{args.ssl_active}"
        create_self_signed_cert(prefix, common_name)
        print(f"created {prefix.name}_cert.pem, {prefix.name}_key.pem, {prefix.name}_ca.pem")


if __name__ == "__main__":
    main()
