#--------------------------------------------------------------------------------------------------------------
# https://www.geeksforgeeks.org/post-query-parameters-in-fastapi/
# select virtual env press ctrl-shift-p  then python:select interpretator
# stop start container will reload directly from this app i.e. not necessariy to build
# ToDo: find container name
# https://stackoverflow.com/questions/62553709/how-to-get-the-name-of-all-container-in-docker-using-docker-py
# https://stackoverflow.com/questions/67663970/optimal-way-to-initialize-heavy-services-only-once-in-fastapi
# https://restfulapi.net/http-methods/
# 
# TODO
# sudo apt install mysql-client-core-8.0
# check on return code 200 - how ?  in the Test
# Build the delete.
# Implement the delete.
# implement the unique control.
# and check how to avoide upload of all the venv stuff...
# check how to start compose in batch... 
#--------------------------------------------------------------------------------------------------------------


import sys, os
if os.path.abspath("..") not in sys.path:
    sys.path.insert(0, os.path.abspath("../.."))
from fastapi import FastAPI, HTTPException, Request
import json
import socket
# import logging
import pn_utilities.PnLogger as PnLogger
#---------------------------------------------------
# set the logging
#---------------------------------------------------
log=PnLogger.PnLogger()
#---------------------------------------------------
# load the crypto environment
#---------------------------------------------------
import pn_utilities.crypto.PnCrypto as PnCrypto

# config file will be taken from PN_CRYPTO_CONFIG_FILE
# when running local just do a:
# export PN_CRYPTO_CONFIG_FILE=config_mysql_localhost.json
# in the terminal window 

crypto_obj = PnCrypto.PnCrypto(os.environ.get('PN_CRYPTO_CONFIG_FILE', 'config.json'))

#---------------------------------------------------
# here we go load the FastAPI
#---------------------------------------------------

app = FastAPI()

#---------------------------------------------------------
# the get index .. root
#---------------------------------------------------------
@app.get("/")
async def root():
    log.info("in root")
    return {"message": "Hello from my World"}

#---------------------------------------------------------
# the get keys list all keys
#---------------------------------------------------------
@app.get("/v1/keys")
async def v1_keys():
    log.info("get keys")
    keys = crypto_obj.get_PnCryptoKeys();
    r_msg = keys.get_keys_json()
    return {r_msg}

#---------------------------------------------------------
# the get a key 
#---------------------------------------------------------
@app.get("/v1/keys/{id}")
async def v1_get_key(id: str):
    log.info("get key called with parameter id:" + id)
    keys = crypto_obj.get_PnCryptoKeys();
    r_msg = keys.get_key_json(id)
    return {r_msg}

#---------------------------------------------------------
# the delete a key 
#---------------------------------------------------------
@app.delete("/v1/keys/{id}")
def delete_key(id: str):
    log.info("delete key called with parameter id:" + id)
    keys = crypto_obj.get_PnCryptoKeys();
    keys.delete_key(id)
    return {"ok": True}
#---------------------------------------------------------
# the post a key 
#---------------------------------------------------------
# @app.route('/v1/keys 
@app.post("/v1/keys")
async def v1_post_key(request: Request):
    log.info("post key called")
    try:
        # Extracting user data from the request body
        data_json = await request.json()
        keys = crypto_obj.get_PnCryptoKeys();

        # Validate the presence of required fields
        log.info("Request received" + data_json)
        if 'id' not in data_json or 'value' not in data_json:
            raise HTTPException(
                status_code=422, detail='Incomplete data provided')

        # parse the dato with json loads and extract f002 and f049
        data = json.loads(data_json)
        
        id = data['id']
        description = data['description']
        value = data['value']
        type = data['type']
        
        keys.import_key(id, description, value, type)
    #    ret_message['arqc'] = crypto_obj.do_arqc(key_name, pan, psn, atc, data, True)
    #    log.info(ret_message)
        return {"ok": True}

    except HTTPException as e:
        # Re-raise HTTPException to return the specified status code and detail
        raise e
    except Exception as e:
        # Handle other unexpected exceptions and return a 500 Internal Server Error
        raise HTTPException(
            status_code=500, detail='An error occurred: {str(e)}')

#-------------------------------------------------------------------------
# post /v1/arqc:  handling request arqc calculate an arqc
#-------------------------------------------------------------------------
@app.post("/v1/arqc")
async def v1_arqc(request: Request):
    hostname = socket.gethostname()
 
    try:
        # Extracting user data from the request body
        data_json = await request.json()
        # Validate the presence of required fields
        log.info("Request received" + data_json)
        if 'pan' not in data_json or 'psn' not in data_json:
            raise HTTPException(
                status_code=422, detail='Incomplete data provided')

        # parse the dato with json loads and extract f002 and f049
        data = json.loads(data_json)
        
        key_name = data['key_name']
        pan = data['pan']
        psn = data['psn']
        atc = data['atc']
        data = data['data']
        ret_message['host'] = hostname
        ret_message['arqc'] = crypto_obj.do_arqc(key_name, pan, psn, atc, data, True)
        log.info(ret_message)
        return {ret_message}

    except HTTPException as e:
        # Re-raise HTTPException to return the specified status code and detail
        raise e
    except Exception as e:
        # Handle other unexpected exceptions and return a 500 Internal Server Error
        raise HTTPException(
            status_code=500, detail='An error occurred: {str(e)}')
#-------------------------------------------------------------------------
# post /v1/arpc:  handling request arpc calculate an arpc
#-------------------------------------------------------------------------
@app.post("/v1/arpc")
async def v1_arpc(request: Request):
    hostname = socket.gethostname()
 
    try:
        # Extracting user data from the request body
        data_json = await request.json()
        # Validate the presence of required fields
        log.info("Request received" + data_json)
        if 'pan' not in data_json or 'psn' not in data_json:
            raise HTTPException(
                status_code=422, detail='Incomplete data provided')

        # parse the dato with json loads and extract f002 and f049
        data = json.loads(data_json)
        
        key_name = data['key_name']
        pan = data['pan']
        psn = data['psn']
        atc = data['atc']
        csu = data['csu']
        arqc = data['arqc']
        ret_message['host'] = hostname
        ret_message['arpc'] = crypto_obj.do_arpc(key_name, pan, psn, atc, arqc, csu)
        # Returning a confirmation message
        log.info(ret_message)
        return {'message': ret_message}

    except HTTPException as e:
        # Re-raise HTTPException to return the specified status code and detail
        raise e
    except Exception as e:
        # Handle other unexpected exceptions and return a 500 Internal Server Error
        raise HTTPException(
            status_code=500, detail='An error occurred: {str(e)}')


#-------------------------------------------------------------------------
# post transcode_0100:  handling request type 0100
#-------------------------------------------------------------------------
@app.post("/transcode_0100")
async def add_transcode_0100(request: Request):
    hostname = socket.gethostname()
 
    try:
        # Extracting user data from the request body
        data_json = await request.json()
        # Validate the presence of required fields
        log.info("Request received" + data_json)
        if 'f002' not in data_json or 'f049' not in data_json:
            raise HTTPException(
                status_code=422, detail='Incomplete data provided')

        # parse the dato with json loads and extract f002 and f049
        data = json.loads(data_json)
        
        pan = data['f002']
        cur = data['f049']

        # Returning a confirmation message
        ret_message = 'host:' + hostname + ': pan and key submitted updated successfully pan:' + pan + ' cur:' + cur
        log.info(ret_message)
        return {'message': ret_message}

    except HTTPException as e:
        # Re-raise HTTPException to return the specified 
        # status code and detail
        print("here")
        raise e
    except Exception as e:
        # Handle other unexpected exceptions and return a 
        # 500 Internal Server Error
        print("ehre two")
        raise HTTPException(
            status_code=500, detail='An error occurred: {str(e)}')


#-----------------------------------------------------------
# we can run it from here or with fastapi dev main.py
#-----------------------------------------------------------
if __name__ == '__main__':
    import uvicorn
    # Run the FastAPI application using uvicorn
    uvicorn.run(app, host='127.0.0.1', port=8080)

