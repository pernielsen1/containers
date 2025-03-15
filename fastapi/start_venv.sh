#!/bin/bash
PWD=`pwd`
echo $PWD
activate () {
  . $PWD/app/bin/activate
}
activate
which pip