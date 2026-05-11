import os
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives import serialization
import datetime

# Create a 'certs' directory in the backend
cert_dir = r"C:\Users\user\Desktop\MTO\backend\certs"
os.makedirs(cert_dir, exist_ok=True)

# Generate private key
key = rsa.generate_private_key(
    public_exponent=65537,
    key_size=2048,
)

# Generate a self-signed certificate
subject = issuer = x509.Name(
    [
        x509.NameAttribute(NameOID.COUNTRY_NAME, "PH"),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "Manila"),
        x509.NameAttribute(NameOID.LOCALITY_NAME, "QC"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "MTO Treasury"),
        x509.NameAttribute(NameOID.COMMON_NAME, "localhost"),
    ]
)
cert = (
    x509.CertificateBuilder()
    .subject_name(subject)
    .issuer_name(issuer)
    .public_key(key.public_key())
    .serial_number(x509.random_serial_number())
    .not_valid_before(datetime.datetime.utcnow())
    .not_valid_after(
        # Our certificate will be valid for 10 years
        datetime.datetime.utcnow()
        + datetime.timedelta(days=3650)
    )
    .add_extension(
        x509.SubjectAlternativeName([x509.DNSName("localhost")]),
        critical=False,
    )
    .sign(key, hashes.SHA256())
)

# Write private key to file
with open(os.path.join(cert_dir, "key.pem"), "wb") as f:
    f.write(
        key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.TraditionalOpenSSL,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )

# Write certificate to file
with open(os.path.join(cert_dir, "cert.pem"), "wb") as f:
    f.write(cert.public_bytes(serialization.Encoding.PEM))

print(f"Certificates generated successfully in: {cert_dir}")
