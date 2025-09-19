#!/usr/bin/env python3
"""
Generate SSL certificates for the browser viewer servers.
This script creates self-signed certificates for HTTPS support.
"""

import subprocess
import sys
from pathlib import Path

def generate_ssl_certificates():
    """Generate SSL certificates for all browser viewer servers."""
    
    # Define certificate locations
    cert_locations = [
        Path("interactive_tools/ssl"),
        Path("interactive_tools/live_view_sessionreplay/ssl")
    ]
    
    domain = "dcv.teague.live"
    
    for cert_dir in cert_locations:
        cert_dir.mkdir(parents=True, exist_ok=True)
        
        cert_path = cert_dir / "server.crt"
        key_path = cert_dir / "server.key"
        
        # Generate self-signed certificate if it doesn't exist
        if not cert_path.exists() or not key_path.exists():
            print(f"Generating SSL certificate for {cert_dir}...")
            try:
                subprocess.run([
                    "openssl", "req", "-x509", "-newkey", "rsa:4096", "-keyout", str(key_path),
                    "-out", str(cert_path), "-days", "365", "-nodes", "-subj",
                    f"/C=US/ST=State/L=City/O=Organization/CN={domain}"
                ], check=True, capture_output=True)
                print(f"✅ SSL certificate generated successfully at {cert_dir}")
            except subprocess.CalledProcessError as e:
                print(f"❌ Failed to generate SSL certificate: {e}")
                print(f"   Error output: {e.stderr.decode() if e.stderr else 'No error output'}")
                return False
            except FileNotFoundError:
                print("❌ OpenSSL not found. Please install OpenSSL:")
                print("   Ubuntu/Debian: sudo apt-get install openssl")
                print("   CentOS/RHEL: sudo yum install openssl")
                print("   macOS: brew install openssl")
                return False
        else:
            print(f"✅ SSL certificate already exists at {cert_dir}")
    
    print("\n🎉 All SSL certificates are ready!")
    print("The browser viewer servers will now use HTTPS to avoid mixed content issues.")
    return True

if __name__ == "__main__":
    success = generate_ssl_certificates()
    sys.exit(0 if success else 1)
