#!/usr/bin/env python3
"""
Test script to verify domain configuration and SSL setup for dcv.teague.live.
This script checks DNS resolution, SSL certificates, and configuration files.
"""

import socket
import ssl
import subprocess
import sys
from pathlib import Path
import requests
from urllib.parse import urlparse

def test_dns_resolution(domain):
    """Test if the domain resolves to an IP address."""
    print(f"🔍 Testing DNS resolution for {domain}...")
    try:
        ip_address = socket.gethostbyname(domain)
        print(f"✅ {domain} resolves to {ip_address}")
        return True, ip_address
    except socket.gaierror as e:
        print(f"❌ DNS resolution failed for {domain}: {e}")
        return False, None

def test_ssl_certificate(domain, port=443):
    """Test SSL certificate for the domain."""
    print(f"🔐 Testing SSL certificate for {domain}:{port}...")
    try:
        context = ssl.create_default_context()
        with socket.create_connection((domain, port), timeout=10) as sock:
            with context.wrap_socket(sock, server_hostname=domain) as ssock:
                cert = ssock.getpeercert()
                print(f"✅ SSL certificate found for {domain}")
                print(f"   Subject: {cert.get('subject', 'Unknown')}")
                print(f"   Issuer: {cert.get('issuer', 'Unknown')}")
                print(f"   Valid until: {cert.get('notAfter', 'Unknown')}")
                return True, cert
    except Exception as e:
        print(f"❌ SSL certificate test failed for {domain}:{port}: {e}")
        return False, None

def check_letsencrypt_certificates(domain):
    """Check if Let's Encrypt certificates exist."""
    print(f"📋 Checking Let's Encrypt certificates for {domain}...")
    
    cert_path = Path(f"/etc/letsencrypt/live/{domain}/fullchain.pem")
    key_path = Path(f"/etc/letsencrypt/live/{domain}/privkey.pem")
    
    if cert_path.exists() and key_path.exists():
        print(f"✅ Let's Encrypt certificates found at /etc/letsencrypt/live/{domain}/")
        
        # Check certificate details
        try:
            result = subprocess.run([
                'openssl', 'x509', '-in', str(cert_path), '-text', '-noout'
            ], capture_output=True, text=True, check=True)
            
            # Extract key information
            lines = result.stdout.split('\n')
            for line in lines:
                if 'Not After' in line:
                    print(f"   Expires: {line.strip()}")
                elif 'DNS:' in line:
                    print(f"   Domains: {line.strip()}")
                    break
            
            return True
        except subprocess.CalledProcessError as e:
            print(f"⚠️  Could not read certificate details: {e}")
            return True  # Certificates exist but can't read details
    else:
        print(f"❌ Let's Encrypt certificates not found for {domain}")
        print(f"   Expected: {cert_path}")
        print(f"   Expected: {key_path}")
        return False

def check_project_certificates():
    """Check if project SSL certificates exist."""
    print("📋 Checking project SSL certificates...")
    
    cert_locations = [
        Path("interactive_tools/ssl"),
        Path("interactive_tools/live_view_sessionreplay/ssl")
    ]
    
    found_any = False
    for cert_dir in cert_locations:
        cert_path = cert_dir / "server.crt"
        key_path = cert_dir / "server.key"
        
        if cert_path.exists() and key_path.exists():
            print(f"✅ Project certificates found in {cert_dir}")
            found_any = True
        else:
            print(f"❌ Project certificates missing in {cert_dir}")
    
    return found_any

def check_configuration_files():
    """Check if configuration files have been updated with the domain."""
    print("📋 Checking configuration files for domain updates...")
    
    files_to_check = [
        "interactive_tools/browser_viewer.py",
        "interactive_tools/live_view_sessionreplay/browser_viewer_replay.py",
        "interactive_tools/live_view_sessionreplay/session_replay_viewer.py",
        "interactive_tools/live_view_sessionreplay/view_recordings.py",
        "interactive_tools/live_view_sessionreplay/browser_interactive_session.py",
        "generate_ssl_certs.py"
    ]
    
    domain = "dcv.teague.live"
    old_ip = "3.140.170.242"
    
    all_updated = True
    for file_path in files_to_check:
        path = Path(file_path)
        if path.exists():
            content = path.read_text()
            if domain in content:
                if old_ip in content:
                    print(f"⚠️  {file_path}: Contains both domain and old IP")
                    all_updated = False
                else:
                    print(f"✅ {file_path}: Updated to use domain")
            else:
                print(f"❌ {file_path}: Domain not found")
                all_updated = False
        else:
            print(f"❌ {file_path}: File not found")
            all_updated = False
    
    return all_updated

def test_http_connection(domain, port=80):
    """Test HTTP connection to the domain."""
    print(f"🌐 Testing HTTP connection to {domain}:{port}...")
    try:
        response = requests.get(f"http://{domain}:{port}", timeout=10)
        print(f"✅ HTTP connection successful (Status: {response.status_code})")
        return True
    except Exception as e:
        print(f"❌ HTTP connection failed: {e}")
        return False

def test_https_connection(domain, port=443):
    """Test HTTPS connection to the domain."""
    print(f"🔒 Testing HTTPS connection to {domain}:{port}...")
    try:
        response = requests.get(f"https://{domain}:{port}", timeout=10, verify=False)
        print(f"✅ HTTPS connection successful (Status: {response.status_code})")
        return True
    except Exception as e:
        print(f"❌ HTTPS connection failed: {e}")
        return False

def main():
    """Main function to run all tests."""
    domain = "dcv.teague.live"
    
    print("🚀 Domain and SSL Configuration Test")
    print("=" * 50)
    print(f"Testing domain: {domain}")
    print()
    
    # Test DNS resolution
    dns_ok, ip_address = test_dns_resolution(domain)
    print()
    
    # Check configuration files
    config_ok = check_configuration_files()
    print()
    
    # Check Let's Encrypt certificates
    letsencrypt_ok = check_letsencrypt_certificates(domain)
    print()
    
    # Check project certificates
    project_certs_ok = check_project_certificates()
    print()
    
    # Test SSL certificate (if DNS resolves)
    ssl_ok = False
    if dns_ok:
        ssl_ok, _ = test_ssl_certificate(domain)
        print()
    
    # Test connections (if DNS resolves)
    http_ok = False
    https_ok = False
    if dns_ok:
        http_ok = test_http_connection(domain)
        print()
        https_ok = test_https_connection(domain)
        print()
    
    # Summary
    print("📊 Test Summary")
    print("=" * 50)
    print(f"DNS Resolution: {'✅' if dns_ok else '❌'}")
    print(f"Configuration Files: {'✅' if config_ok else '❌'}")
    print(f"Let's Encrypt Certs: {'✅' if letsencrypt_ok else '❌'}")
    print(f"Project Certificates: {'✅' if project_certs_ok else '❌'}")
    print(f"SSL Certificate: {'✅' if ssl_ok else '❌'}")
    print(f"HTTP Connection: {'✅' if http_ok else '❌'}")
    print(f"HTTPS Connection: {'✅' if https_ok else '❌'}")
    print()
    
    # Recommendations
    print("💡 Recommendations")
    print("=" * 50)
    
    if not dns_ok:
        print("❗ DNS resolution failed. Ensure the domain points to your server's IP address.")
    
    if not config_ok:
        print("❗ Configuration files need updates. Run the domain update script.")
    
    if not letsencrypt_ok and not project_certs_ok:
        print("❗ No SSL certificates found. Run: sudo python3 setup_letsencrypt_ssl.py")
    elif not letsencrypt_ok:
        print("💡 Consider using Let's Encrypt for production: sudo python3 setup_letsencrypt_ssl.py")
    
    if dns_ok and not ssl_ok:
        print("❗ SSL certificate issues detected. Check certificate validity and domain configuration.")
    
    if dns_ok and not https_ok:
        print("❗ HTTPS connection failed. Ensure your application is running with SSL enabled.")
    
    # Overall status
    overall_ok = dns_ok and config_ok and (letsencrypt_ok or project_certs_ok)
    print()
    if overall_ok:
        print("🎉 Domain and SSL configuration looks good!")
    else:
        print("⚠️  Some issues detected. Please address the recommendations above.")
    
    return 0 if overall_ok else 1

if __name__ == "__main__":
    sys.exit(main())
