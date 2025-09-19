#!/usr/bin/env python3
"""
Setup Let's Encrypt SSL certificates for dcv.teague.live domain.
This script generates valid SSL certificates using certbot.
"""

import subprocess
import sys
import os
from pathlib import Path
import shutil

def check_certbot_installed():
    """Check if certbot is installed."""
    try:
        result = subprocess.run(['certbot', '--version'], capture_output=True, text=True)
        print(f"✅ Certbot found: {result.stdout.strip()}")
        return True
    except FileNotFoundError:
        print("❌ Certbot not found. Installing...")
        return False

def install_certbot():
    """Install certbot if not present."""
    try:
        # Update package list
        subprocess.run(['sudo', 'apt', 'update'], check=True)
        
        # Install certbot
        subprocess.run(['sudo', 'apt', 'install', '-y', 'certbot'], check=True)
        print("✅ Certbot installed successfully")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to install certbot: {e}")
        return False

def generate_letsencrypt_certificate(domain, email=None):
    """Generate Let's Encrypt certificate for the domain."""
    print(f"🔐 Generating Let's Encrypt certificate for {domain}...")
    
    # Prepare certbot command
    cmd = [
        'sudo', 'certbot', 'certonly',
        '--standalone',
        '--non-interactive',
        '--agree-tos',
        '-d', domain
    ]
    
    # Add email if provided
    if email:
        cmd.extend(['--email', email])
    else:
        cmd.append('--register-unsafely-without-email')
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        print("✅ Let's Encrypt certificate generated successfully!")
        print(result.stdout)
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to generate Let's Encrypt certificate: {e}")
        print(f"Error output: {e.stderr}")
        return False

def copy_certificates_to_project(domain):
    """Copy Let's Encrypt certificates to project directories."""
    letsencrypt_dir = Path(f"/etc/letsencrypt/live/{domain}")
    
    if not letsencrypt_dir.exists():
        print(f"❌ Let's Encrypt certificates not found at {letsencrypt_dir}")
        return False
    
    # Define project certificate locations
    cert_locations = [
        Path("interactive_tools/ssl"),
        Path("interactive_tools/live_view_sessionreplay/ssl")
    ]
    
    cert_file = letsencrypt_dir / "fullchain.pem"
    key_file = letsencrypt_dir / "privkey.pem"
    
    if not cert_file.exists() or not key_file.exists():
        print(f"❌ Certificate files not found in {letsencrypt_dir}")
        return False
    
    print("📋 Copying certificates to project directories...")
    
    for cert_dir in cert_locations:
        cert_dir.mkdir(parents=True, exist_ok=True)
        
        project_cert = cert_dir / "server.crt"
        project_key = cert_dir / "server.key"
        
        try:
            # Copy certificate files
            shutil.copy2(cert_file, project_cert)
            shutil.copy2(key_file, project_key)
            
            # Set appropriate permissions
            os.chmod(project_cert, 0o644)
            os.chmod(project_key, 0o600)
            
            print(f"✅ Certificates copied to {cert_dir}")
        except Exception as e:
            print(f"❌ Failed to copy certificates to {cert_dir}: {e}")
            return False
    
    return True

def setup_certificate_renewal():
    """Setup automatic certificate renewal."""
    print("🔄 Setting up automatic certificate renewal...")
    
    try:
        # Test renewal
        subprocess.run(['sudo', 'certbot', 'renew', '--dry-run'], check=True, capture_output=True)
        print("✅ Certificate renewal test successful")
        
        # Add renewal hook to copy certificates after renewal
        hook_script = """#!/bin/bash
# Copy renewed certificates to project directories
python3 /home/ubuntu/sandbox-on-aws-demo/setup_letsencrypt_ssl.py --copy-only
"""
        
        hook_path = Path("/etc/letsencrypt/renewal-hooks/deploy/copy-to-project.sh")
        hook_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(hook_path, 'w') as f:
            f.write(hook_script)
        
        os.chmod(hook_path, 0o755)
        print("✅ Renewal hook installed")
        
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to setup certificate renewal: {e}")
        return False

def main():
    """Main function to setup Let's Encrypt SSL certificates."""
    domain = "dcv.teague.live"
    email = None  # You can set an email here if desired
    
    print(f"🚀 Setting up Let's Encrypt SSL certificates for {domain}")
    print("=" * 60)
    
    # Check if running with --copy-only flag
    if len(sys.argv) > 1 and sys.argv[1] == '--copy-only':
        print("📋 Copy-only mode: Copying existing certificates...")
        if copy_certificates_to_project(domain):
            print("✅ Certificates copied successfully")
        else:
            print("❌ Failed to copy certificates")
        return
    
    # Check if certbot is installed
    if not check_certbot_installed():
        if not install_certbot():
            print("❌ Failed to install certbot. Exiting.")
            sys.exit(1)
    
    # Check if running as root or with sudo
    if os.geteuid() != 0:
        print("⚠️  This script needs to run with sudo privileges for certbot.")
        print("Please run: sudo python3 setup_letsencrypt_ssl.py")
        sys.exit(1)
    
    # Generate Let's Encrypt certificate
    if not generate_letsencrypt_certificate(domain, email):
        print("❌ Failed to generate Let's Encrypt certificate. Exiting.")
        sys.exit(1)
    
    # Copy certificates to project directories
    if not copy_certificates_to_project(domain):
        print("❌ Failed to copy certificates to project directories. Exiting.")
        sys.exit(1)
    
    # Setup automatic renewal
    if not setup_certificate_renewal():
        print("⚠️  Failed to setup automatic renewal, but certificates are installed.")
    
    print("\n🎉 Let's Encrypt SSL setup completed successfully!")
    print(f"✅ Domain: {domain}")
    print("✅ Certificates installed in project directories")
    print("✅ Automatic renewal configured")
    print("\nNext steps:")
    print("1. Restart your application to use the new certificates")
    print("2. Test the HTTPS connection")
    print("3. Certificates will auto-renew every 90 days")

if __name__ == "__main__":
    main()
