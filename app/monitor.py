"""AN-only operational alerts. Never include names, links, IPs or credentials."""
import json
import os
from pathlib import Path
import smtplib
import ssl
import subprocess
import time
from email.message import EmailMessage

MAILBOX = 'kontakt@abrechnungs-navi.de'
LABELS = {'service_down':'AN-Anwendung nicht aktiv',
          'backup_stale':'Taegliche Sicherung fehlt oder ist zu alt',
          'backup_failed':'Sicherungslauf fehlgeschlagen',
          'deletion_failed':'Faellige Loeschung fehlgeschlagen',
          'cleanup_failed':'Automatischer Loeschlauf fehlgeschlagen',
          'cleanup_stale':'Aktuelle Loeschkontrolle fehlt'}

def collect(data, config, active, now):
    issues = set()
    if not active: issues.add('service_down')
    try:
        if now-float((config/'backup-last-success').read_text()) > 26*3600: issues.add('backup_stale')
    except (OSError, ValueError): issues.add('backup_stale')
    try:
        if float((config/'backup-last-failure').read_text()) > float((config/'backup-last-success').read_text()): issues.add('backup_failed')
    except (OSError, ValueError): pass
    try:
        health=json.loads((data/'cleanup-health.json').read_text())
        if health.get('failed_deletions',0): issues.add('deletion_failed')
        if health.get('cleanup_error'): issues.add('cleanup_failed')
        if now-float(health.get('last_attempt',0)) > 2*3600: issues.add('cleanup_stale')
    except (OSError, ValueError, TypeError): issues.add('cleanup_stale')
    return sorted(issues)

def send_alert(issues, smtp_file, test=False):
    msg=EmailMessage()
    msg['From']='Abrechnungs-Navi Sicherheitsueberwachung <'+MAILBOX+'>'
    msg['To']=MAILBOX
    msg['Subject']='TEST Abrechnungs-Navi – Sicherheitsüberwachung' if test else 'Abrechnungs-Navi – Sicherheitswarnung'
    msg.set_content(('Freigegebener Funktionstest. Kuenstlich ausgeloester Loeschfehler; keine echte Kundenstoerung.\n\n' if test else 'Bitte Stoerung pruefen und die Behebung dokumentieren.\n\n')+'\n'.join('- '+LABELS[x] for x in issues)+'\n\nEs werden keine Kunden-/Mieterdaten, Zugangsdaten, IP-Adressen oder Links mitgeschickt.\n')
    with smtplib.SMTP('smtp.hostinger.com',587,timeout=20) as smtp:
        smtp.starttls(context=ssl.create_default_context())
        smtp.login(MAILBOX,smtp_file.read_text().strip())
        refused=smtp.send_message(msg)
        if refused: raise RuntimeError('mail_recipient_rejected')

def run(data, config, state_file, active, now=None, sender=send_alert):
    now = time.time() if now is None else now
    issues=collect(data,config,active,now)
    try: state=json.loads(state_file.read_text())
    except (OSError,ValueError): state={}
    previous=state.get('issues',[])
    due=bool(issues) and (issues!=previous or now-float(state.get('last_sent',0)) >= 24*3600)
    if due:
        # Failure leaves the previous state intact, so the next timer run retries.
        sender(issues,config/'smtp.conf')
        state['last_sent']=now
    state.update({'checked_at':now,'issues':issues})
    state_file.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
    temp=state_file.with_suffix('.tmp');temp.write_text(json.dumps(state));os.chmod(temp,0o600);os.replace(temp,state_file)
    return {'issues':issues,'notification_sent':due}

if __name__=='__main__':
    active=(subprocess.run(['systemctl','is-active','--quiet','an-upload']).returncode==0 or
            subprocess.run(['systemctl','is-active','--quiet','an-backup']).returncode==0)
    try:
        result=run(Path('/srv/an-upload/data'),Path('/etc/an-upload'),Path('/var/lib/an-monitor/state.json'),active)
        print(json.dumps(result))
    except Exception as error:
        print('AN monitoring failed: '+type(error).__name__,flush=True)
        raise SystemExit(1)
