{
  description = "Goose FM Radio Server";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    flake-utils.url = "github:numtide/flake-utils";
    poetry2nix = {
      url = "github:nix-community/poetry2nix";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = { self, nixpkgs, flake-utils, poetry2nix }:
    let
      supportedSystems = [ "x86_64-linux" "aarch64-linux" "x86_64-darwin" "aarch64-darwin" ];
    in
    flake-utils.lib.eachSystem supportedSystems (system:
      let
        pkgs = nixpkgs.legacyPackages.${system};
        poetry2nixPkgs = poetry2nix.lib.mkPoetry2Nix { inherit pkgs; };

        # System dependencies
        systemDeps = with pkgs; [
          sox    # For audio processing
          rtl-sdr # For SDR functionality
          poetry
          python310
        ];

        # Python package of MCP service
        gooseFmPackage = poetry2nixPkgs.mkPoetryApplication {
          projectDir = ./.;

	  propegatedBuildInputs = with pkgs; [
	    sox
	    rtl-sdr
	  ];
          
          # Prefer wheels for faster builds
          preferWheels = true;
        };

        # Create a wrapper script to run radio_server.py with runtime inputs
        runScript = pkgs.writeShellApplication {
	  name = "goose-fm";
	  runtimeInputs = [ pkgs.sox pkgs.rtl-sdr ];
	  text = ''
          ${gooseFmPackage.dependencyEnv}/bin/python ${./radio_server.py}
        '';
	};

      in {
        packages = {
          default = gooseFmPackage;
        };

        apps = {
          default = {
            type = "app";
            program = "${runScript}/bin/goose-fm";
          };
        };

        devShells.default = pkgs.mkShell {
          buildInputs = systemDeps ++ [
            gooseFmPackage.dependencyEnv
            pkgs.poetry
            runScript
          ];
        };
      });
}
