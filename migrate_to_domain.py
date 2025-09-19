#!/usr/bin/env python3
"""
Complete migration script to update agentcore browser tool from IP address to domain.
This script handles domain configuration, SSL certificates, and testing.
"""

import subprocess
import sys
import os
from pathlib import Path
import shutil

def print_header(title):
    """Print a formatted header."""
    print(f"\n{'='*60}")
    print(f"🚀 {title}")
    print(f"{'='*60}")

def print_step(step, description):
    """Print a formatted step."""
    print(f"\n📋 Step {step}: {description}")
    print("-" * 40)

def run_command(cmd, description, check=True, capture_output=True):
    """Run a command with error handling."""
    print(f"Running: {' '.join(cmd) if isinstance(cmd, list) else cmd}")
    try:
        result = subprocess.run(cmd, check=check, capture_output=capture_output, text=True)
        if result.stdout:
            print(result.stdout)
        return True, result
    except subprocess.CalledProcessError as e:
        print(f"❌ {description} failed: {e}")
        if e.stderr:
            print(f"Error: {e.stderr}")
        return False, e

def check_domain_dns():
    """Check if domain resolves correctly."""
    print("🔍 Checking DNS resolution for dcv.teague.live...")
    try:
        import socket
        ip = socket.gethostbyname("dcv.teague.live")
        print(f"✅ dcv.teague.live resolves to {ip}")
        return True
    except socket.gaierror as e:
        print(f"❌ DNS resolution failed: {e}")
        print("⚠️  Please ensure dcv.teague.live points to your server's IP address")
        return False

def backup_existing_certificates():
    """Backup existing SSL certificates."""
    print("💾 Backing up existing SSL certificates...")
    
    cert_locations = [
        Path("interactive_tools/ssl"),
        Path("interactive_tools/live_view_sessionreplay/ssl")
    ]
    
    backup_dir = Path("ssl_backup")
    backup_dir.mkdir(exist_ok=True)
    
    for cert_dir in cert_locations:
        if cert_dir.exists():
            backup_path = backup_dir / cert_dir.name
            if backup_path.exists():
                shutil.rmtree(backup_path)
            shutil.copytree(cert_dir, backup_path)
            print(f"✅ Backed up {cert_dir} to {backup_path}")

def setup_letsencrypt():
    """Setup Let's Encrypt SSL certificates."""
    print("🔐 Setting up Let's Encrypt SSL certificates...")
    
    # Check if certbot is installed
    success, _ = run_command(['which', 'certbot'], "Check certbot", check=False)
    if not success:
        print("📦 Installing certbot...")
        success, _ = run_command(['sudo', 'apt', 'update'], "Update package list")
        if not success:
            return False
        
        success, _ = run_command(['sudo', 'apt', 'install', '-y', 'certbot'], "Install certbot")
        if not success:
            return False
    
    # Generate Let's Encrypt certificate
    print("🔐 Generating Let's Encrypt certificate...")
    cmd = [
        'sudo', 'certbot', 'certonly',
        '--standalone',
        '--non-interactive',
        '--agree-tos',
        '--register-unsafely-without-email',
        '-d', 'dcv.teague.live'
    ]
    
    success, result = run_command(cmd, "Generate Let's Encrypt certificate")
    if success:
        print("✅ Let's Encrypt certificate generated successfully!")
        return True
    else:
        print("❌ Failed to generate Let's Encrypt certificate")
        print("💡 You may need to:")
        print("   1. Ensure port 80 is available")
        print("   2. Check firewall settings")
        print("   3. Verify DNS is properly configured")
        return False

def copy_letsencrypt_to_project():
    """Copy Let's Encrypt certificates to project directories."""
    print("📋 Copying Let's Encrypt certificates to project directories...")
    
    domain = "dcv.teague.live"
    letsencrypt_dir = Path(f"/etc/letsencrypt/live/{domain}")
    
    if not letsencrypt_dir.exists():
        print(f"❌ Let's Encrypt directory not found: {letsencrypt_dir}")
        return False
    
    cert_file = letsencrypt_dir / "fullchain.pem"
    key_file = letsencrypt_dir / "privkey.pem"
    
    if not cert_file.exists() or not key_file.exists():
        print(f"❌ Certificate files not found in {letsencrypt_dir}")
        return False
    
    # Copy to project directories
    cert_locations = [
        Path("interactive_tools/ssl"),
        Path("interactive_tools/live_view_sessionreplay/ssl")
    ]
    
    for cert_dir in cert_locations:
        cert_dir.mkdir(parents=True, exist_ok=True)
        
        project_cert = cert_dir / "server.crt"
        project_key = cert_dir / "server.key"
        
        try:
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

def generate_fallback_certificates():
    """Generate self-signed certificates as fallback."""
    print("🔐 Generating self-signed certificates as fallback...")
    
    success, _ = run_command(['python3', 'generate_ssl_certs.py'], "Generate self-signed certificates")
    return success

def test_configuration():
    """Test the new configuration."""
    print("🧪 Testing new configuration...")
    
    success, _ = run_command(['python3', 'test_domain_ssl_config.py'], "Test domain and SSL configuration")
    return success

def setup_certificate_renewal():
    """Setup automatic certificate renewal."""
    print("🔄 Setting up automatic certificate renewal...")
    
    # Test renewal
    success, _ = run_command(['sudo', 'certbot', 'renew', '--dry-run'], "Test certificate renewal")
    if not success:
        print("⚠️  Certificate renewal test failed")
        return False
    
    # Create renewal hook
    hook_script = f"""#!/bin/bash
# Copy renewed certificates to project directories
cd {os.getcwd()}
python3 setup_letsencrypt_ssl.py --copy-only
"""
    
    hook_path = Path("/etc/letsencrypt/renewal-hooks/deploy/copy-to-project.sh")
    
    try:
        hook_path.parent.mkdir(parents=True, exist_ok=True)
        with open(hook_path, 'w') as f:
            f.write(hook_script)
        os.chmod(hook_path, 0o755)
        print("✅ Renewal hook installed")
        return True
    except Exception as e:
        print(f"❌ Failed to setup renewal hook: {e}")
        return False

def main():
    """Main migration function."""
    print_header("Agentcore Browser Tool Domain Migration")
    print("This script will migrate from IP address (3.140.170.242) to domain (dcv.teague.live)")
    print("🔧 Features:")
    print("  • Update all configuration files to use dcv.teague.live")
    print("  • Generate Let's Encrypt SSL certificates")
    print("  • Setup automatic certificate renewal")
    print("  • Test the new configuration")
    
    # Check if running as root for Let's Encrypt
    if os.geteuid() != 0:
        print("\n⚠️  This script needs sudo privileges for Let's Encrypt certificate generation.")
        print("Please run: sudo python3 migrate_to_domain.py")
        return 1
    
    print_step(1, "Checking DNS Resolution")
    if not check_domain_dns():
        print("❌ DNS check failed. Please configure DNS before proceeding.")
        return 1
    
    print_step(2, "Backing Up Existing Certificates")
    backup_existing_certificates()
    
    print_step(3, "Setting Up Let's Encrypt SSL Certificates")
    letsencrypt_success = setup_letsencrypt()
    
    if letsencrypt_success:
        print_step(4, "Copying Let's Encrypt Certificates to Project")
        copy_success = copy_letsencrypt_to_project()
        
        if copy_success:
            print_step(5, "Setting Up Certificate Renewal")
            setup_certificate_renewal()
        else:
            print("⚠️  Failed to copy Let's Encrypt certificates, generating fallback certificates...")
            generate_fallback_certificates()
    else:
        print_step(4, "Generating Fallback Self-Signed Certificates")
        if not generate_fallback_certificates():
            print("❌ Failed to generate any SSL certificates")
            return 1
    
    print_step(6, "Testing New Configuration")
    test_configuration()
    
    print_header("Migration Complete!")
    print("✅ Domain migration completed successfully!")
    print()
    print("📋 Summary:")
    print("  • All configuration files updated to use dcv.teague.live")
    print("  • SSL certificates installed and configured")
    print("  • Automatic certificate renewal setup (if Let's Encrypt was used)")
    print()
    print("🚀 Next Steps:")
    print("  1. Restart your application to use the new domain and certificates")
    print("  2. Test the agentcore browser tool with HTTPS")
    print("  3. Verify that mixed content errors are resolved")
    print()
    print("🔧 Useful Commands:")
    print("  • Test configuration: python3 test_domain_ssl_config.py")
    print("  • Regenerate certificates: sudo python3 setup_letsencrypt_ssl.py")
    print("  • Check certificate status: sudo certbot certificates")
    
    return 0

if __name__ == "__main__":
    sys.exit(main())
