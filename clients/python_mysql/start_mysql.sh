#!/bin/bash
sudo service mysql start
pause 20
sudo mysql -h localhost -u root -ppassword test_db