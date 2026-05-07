# MTO Client Test Setup

Use this guide when testing the MTO app from another PC on the same network.

## 1. Server PC checklist

Server PC IP:

`192.168.1.151`

Make sure the server PC is powered on and connected to the same LAN or Wi-Fi as the client PC.

Make sure MySQL is running on the server PC.

If you use XAMPP:

1. Open XAMPP Control Panel.
2. Start `MySQL`.
3. Confirm the `property_system` database exists.

Make sure Windows Firewall allows inbound TCP port `3306`.

Example PowerShell command on the server PC:

```powershell
New-NetFirewallRule -DisplayName "MTO MySQL 3306" -Direction Inbound -Protocol TCP -LocalPort 3306 -Action Allow
```

Make sure MySQL allows remote TCP connections.

Check your MySQL config file, usually `my.ini`, and verify:

```ini
[mysqld]
bind-address=0.0.0.0
port=3306
```

If `bind-address` is set to `127.0.0.1`, client PCs will not be able to connect.

After changing `my.ini`, restart MySQL.

Make sure the MySQL user can connect from other machines.

For quick testing only, you can run this in phpMyAdmin or MySQL:

```sql
CREATE USER IF NOT EXISTS 'root'@'%' IDENTIFIED BY '';
GRANT ALL PRIVILEGES ON property_system.* TO 'root'@'%';
FLUSH PRIVILEGES;
```

If your MySQL already uses `root`, update the existing remote-access rule instead of creating duplicates.

## 2. Client PC checklist

Copy the MTO project folder to the client PC.

Open the project folder and run:

```powershell
install_packages.bat
```

Replace `db_config.json` with the client-ready file:

1. Keep a backup of the original `db_config.json`.
2. Copy `db_config.client.json`.
3. Rename the copy to `db_config.json`.

Run the network test:

```powershell
python network_test.py
```

Expected result:

- Socket connection succeeds.
- MySQL login succeeds.

Then start the app:

```powershell
python main.py
```

## 3. Quick troubleshooting

If `network_test.py` says socket connection failed:

- Check both PCs are on the same network.
- Check the server IP is still `192.168.1.151`.
- Check Windows Firewall on the server.
- Check MySQL is running.
- Check `bind-address` is not `127.0.0.1`.

If socket works but MySQL login fails:

- Check MySQL username and password.
- Check the database name is `property_system`.
- Check the MySQL user is allowed from `%` or from the client PC IP.

If the app does not start at all:

- Make sure Python is installed on the client PC.
- Run `install_packages.bat`.
- Try `python network_test.py` first to confirm dependencies and DB access.
