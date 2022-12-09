# Latest Maian with solc 0.5.10
docker build .
#...
#Successfully built <IMAGE ID>
docker image rm solscan/maian:solc5.10
docker tag <IMAGE ID> solscan/maian:solc5.10
docker push solscan/maian:solc5.10

# Latest Maian with solc 0.4.25
docker build --build-arg SOLC_VERSION=0.4.25 .
#...
#Successfully built <IMAGE ID>
docker image rm solscan/maian:solc4.25
docker tag <IMAGE ID> solscan/maian:solc4.25
docker push solscan/maian:solc4.25

# Specific Maian <commit> with specific Solc <version>
docker build --build-arg MAIAN_COMMIT=<commit> --build-arg SOLC_VERSION=<version> .
#...
#Successfully built <IMAGE ID>
docker image rm solscan/maian:<tag>
docker tag <IMAGE ID> solscan/maian:<tag>
docker push solscan/maian:<commit>
