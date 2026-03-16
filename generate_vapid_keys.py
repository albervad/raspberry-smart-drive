import base64
import json
import sys


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def main() -> int:
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec
    except Exception:
        print(
            "No se pudo importar 'cryptography'. Instala dependencias con: pip install -r requirements.txt",
            file=sys.stderr,
        )
        return 1

    private_key = ec.generate_private_key(ec.SECP256R1())
    private_number = private_key.private_numbers().private_value
    private_bytes = private_number.to_bytes(32, "big")

    public_bytes = private_key.public_key().public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint,
    )

    payload = {
        "publicKey": _b64url(public_bytes),
        "privateKey": _b64url(private_bytes),
    }

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
