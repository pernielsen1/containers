#--------------------------------------------------------------------------------------------------------------
#--------------------------------------------------------------------------------------------------------------


import sys, os
if os.path.abspath("..") not in sys.path:
    sys.path.insert(0, os.path.abspath("../.."))
from fastapi import FastAPI, HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

import json
import socket
from pydantic import BaseModel

#--------------------------------------------------------------------------------------------
# perhaps candidates for a shared object with keys in crypto or ? should it be local here? 
#-------------------------------------------------------------------------------------------
class CryptoKeyInput(BaseModel):
    id: str
    description: str
    value: str
    type: str

#--------------------------------------------------------------------------------------------
# the ARQC / APRC inputs 
#-------------------------------------------------------------------------------------------
class ARQC_Input(BaseModel):
    key_name: str
    pan: str
    psn: str
    atc: str
    data: str

class ARPC_Input(BaseModel):
    key_name: str
    pan: str
    psn: str
    atc: str
    csu: str
    arqc: str

       
# import logging  
import pn_utilities.logger.PnLogger as PnLogger
#---------------------------------------------------
# set the logging
#---------------------------------------------------
log=PnLogger.PnLogger()
#---------------------------------------------------
# load the crypto environment
#---------------------------------------------------
import pn_utilities.crypto.PnCrypto as PnCrypto

# config file will be taken from PN_CRYPTO_CONFIG_FILE
# in container it is config_fastapi_container.json
# in local mode defaulting to config.json = local mysql started.

crypto_obj = PnCrypto.PnCrypto(os.environ.get('PN_CRYPTO_CONFIG_FILE', 'config.json'))

#---------------------------------------------------
# here we go load the FastAPI
#---------------------------------------------------

app = FastAPI()

#--------------------------------------------------------------------------------------------------
# validate_request:  Convert request to dictorionary and perform pydantic plus return dictionary
#-------------------------------------------------------------------------------------------------
def validate_request_and_get_obj(data_json, object_class):
    try:
        log.info("Request received ready to pydantic" + data_json)
        data = json.loads(data_json)
        obj = object_class.model_validate(data)
        log.info("Passed the validation")
        return obj
    except Exception as e:   # just raise it will be logged in calling routine
        raise e
    
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
@app.post("/v1/keys", status_code=201)
async def v1_post_key(request: Request):
    log.info("post key called")
    try:
        # Extracting user data from the request body
        data_json = await request.json()
        # Validate the presence of required fields and returns a CryptoKeyInput object
        CK_obj = validate_request_and_get_obj(data_json, CryptoKeyInput)

        # seems to be OK input let's try to import - we can get duplicate key in key DB :-) 
        keys = crypto_obj.get_PnCryptoKeys();        
        if (keys.import_key(CK_obj.id, CK_obj.description, CK_obj.value, CK_obj.type) == True):
            return {"ok": True}
        else:
            raise HTTPException(
                status_code=422, detail='Key already exists')
    
    except HTTPException as e:
        # Re-raise HTTPException to return the specified status code and detail
        log.error("error:" + str(e)) 
        raise e
  
    except Exception as e:
        # Handle other unexpected exceptions and return a 500 Internal Server Error
        log.error("error:" + str(e))
        raise HTTPException(
            status_code=500, detail='An error occurred:' + str(e))


#-------------------------------------------------------------------------
# post /v1/arqc:  handling request arqc calculate an arqc
#-------------------------------------------------------------------------
@app.post("/v1/arqc")
async def v1_arqc(request: Request):
    hostname = socket.gethostname()
 
    try:
        # Extracting user data from the request body
        data_json = await request.json()
        
        log.info("ARQC Request received" + data_json)
        # parse the dato with json loads and extract AQRC request using pydantic to ARQC_Input object
        ARQC_obj = validate_request_and_get_obj(data_json, ARQC_Input)

        ret_message = {}
        ret_message['host'] = hostname
        ret_message['arqc'] = crypto_obj.do_arqc(ARQC_obj.key_name, ARQC_obj.pan, 
                                                 ARQC_obj.psn, ARQC_obj.atc, ARQC_obj.data, True)
        json_response = jsonable_encoder(ret_message)
        log.info("replying:" + str(json_response))
        return JSONResponse(content=json_response)

    except Exception as e:
        # Handle other unexpected exceptions and return a 500 Internal Server Error
        log.error("error:" + str(e))
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
        log.info("Request received" + data_json)
        
        # parse the dato with json loads and get ARPC_Input object with pydantify 
        ARPC_obj = validate_request_and_get_obj(data_json, ARPC_Input)

        ret_message = {}
        ret_message['host'] = hostname
        ret_message['arpc'] = crypto_obj.do_arpc(ARPC_obj.key_name, ARPC_obj.pan, ARPC_obj.psn, 
                                                 ARPC_obj.atc, ARPC_obj.arqc, ARPC_obj.csu)
        # Returning a confirmation message
        json_response = jsonable_encoder(ret_message)
        log.info("replying:" + str(json_response))
        return JSONResponse(content=json_response)

    except Exception as e:
        # Handle other unexpected exceptions and return a 500 Internal Server Error
        log.error("error:" + str(e))
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

